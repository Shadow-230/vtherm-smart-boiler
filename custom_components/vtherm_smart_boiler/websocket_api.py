"""What the Boiler page reads, and the one change it can make
(``docs/en/development/plans/plan-0.2-i10.md``, I10.2, I10.4 and I10.6).

Read-only, for any signed-in user: the installation as the settings describe it, the curve's
points with the settings' own checks, the daily summaries, the monitor's burns and the journal.
One write, for an administrator
only: the curve saved — through the plugin's own settings, so every check and the save itself
are theirs (I10.4). Each answers from the running entry; with none running, the error
``not_running``. The page computes no law of its own: the curve comes from ``core.curve_view``,
the checks from ``control_config`` and the settings. The commands are registered once per run of
Home Assistant — one cannot be taken back.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, Any

import probatio as vol  # Home Assistant's schemas for WebSocket commands since 2026.10
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import (
    async_response,
    require_admin,
    websocket_command,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType, InvalidData, UnknownFlow, UnknownStep
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, LEVEL, LEVEL_ADVANCED
from .control_config import curve_problems, lowest_above_max
from .core.building import MIN_FIT_DAYS, MIN_OUTDOOR_SPREAD_K
from .core.curve_view import curve_points
from .core.journal import JOURNAL_DAYS, JOURNAL_MAX, entry_to_stored
from .core.parameters import ParameterKey
from .core.signals import Signal
from .core.signature import Signature, SignatureFit, energy_signature
from .core.weekly import weekly_use

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

NOT_RUNNING = "not_running"
WEEKS_SHOWN = 12
NO_CURVE = "no_curve"
INVALID_RANGE = "invalid_range"
INVALID_CURVE = "invalid_curve"  # the values cannot make a curve at all
CURVE_KEYS = ("design_outdoor", "design_flow", "room", "exponent", "offset")
LIMIT_KEYS = ("hard_min", "hard_max")
_DATA = f"{DOMAIN}_websocket"


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register the page's commands, once per run of Home Assistant."""
    if hass.data.get(_DATA):
        return
    for handler in (ws_installation, ws_curve, ws_days, ws_burns, ws_journal, ws_curve_save):
        async_register_command(hass, handler)
    hass.data[_DATA] = True


def _coordinator(hass: HomeAssistant) -> SmartBoilerCoordinator | None:
    """The running entry's coordinator; there is at most one entry."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            coordinator: SmartBoilerCoordinator | None = getattr(entry, "runtime_data", None)
            if coordinator is not None:
                return coordinator
    return None


def _not_running(connection: ActiveConnection, msg: dict[str, Any]) -> None:
    connection.send_error(msg["id"], NOT_RUNNING, "Smart Boiler is not running")


def installation_view(hass: HomeAssistant, coordinator: SmartBoilerCoordinator) -> dict[str, Any]:
    """The installation as the settings describe it, with the plugin's own entities by key and
    the curve's settings — what the page needs to draw the schematic and the curve."""
    config = coordinator.config
    entry = coordinator.config_entry
    installation = config.installation
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    entities = {
        found.unique_id.removeprefix(prefix): found.entity_id
        for found in er.async_entries_for_config_entry(registry, entry.entry_id)
        if found.unique_id.startswith(prefix)
    }
    boiler = installation.boiler
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "boiler": {
            "type": None if config.panel.boiler_type is None else config.panel.boiler_type.value,
            "dhw": boiler.dhw.value,
            "condensing": boiler.condensing,
        },
        "circuits": [
            {
                "id": circuit.circuit_id,
                "name": config.circuit_names.get(circuit.circuit_id, circuit.circuit_id),
                "control": circuit.control.value,
                "fixed_temperature": circuit.fixed_temperature,
                "max_flow": circuit.max_flow,
                "needed": circuit.needed,
                "zones": [
                    {"entity_id": zone.zone_id, "emitter": zone.emitter.value}
                    for zone in installation.zones
                    if zone.circuit_id == circuit.circuit_id
                ],
            }
            for circuit in installation.circuits
        ],
        "signals": {signal.value: entity_id for signal, entity_id in config.signals.items()},
        "weather": config.weather,
        "entities": dict(sorted(entities.items())),
        "curve": _curve_settings(coordinator),
        # The monitor's own short-burn length, so the page marks short burns as the monitor does.
        "short_burn_min": config.monitor.monitor.short_burn_s / 60.0,
    }


def _curve_settings(coordinator: SmartBoilerCoordinator) -> dict[str, Any] | None:
    """The curve's settings where control sets the water; ``None`` otherwise (monitoring only,
    or a relay that switches heating on and off)."""
    control = coordinator.config.control
    loop = control.loop.control
    if not control.configured or loop.on_off:
        return None
    curve, limits = loop.curve, loop.limits
    return {
        "entered": control.curve_entered,
        "design_outdoor": curve.design_outdoor,
        "design_flow": curve.design_flow,
        "room": curve.room,
        "exponent": curve.exponent,
        "offset": curve.offset,
        "hard_min": limits.hard_min,
        "hard_max": limits.hard_max,
        "circuit_max": loop.circuit_max,
        "boiler_max": loop.boiler_max,
        "room_auto": loop.room_auto,
        "comfort_correction": loop.comfort_correction,
        "correction_max_k": loop.correction_max_k,
        # The settings' advanced level shows the offset: only then can the page save it.
        "advanced": coordinator.config_entry.options.get(LEVEL) == LEVEL_ADVANCED,
    }


@websocket_command({vol.Required("type"): f"{DOMAIN}/installation"})
@callback
def ws_installation(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_running(connection, msg)
        return
    connection.send_result(msg["id"], installation_view(hass, coordinator))


_OUTDOOR = vol.All(vol.Coerce(float), vol.Range(min=-40.0, max=40.0))


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/curve",
        **{vol.Optional(key): vol.Coerce(float) for key in (*CURVE_KEYS, *LIMIT_KEYS)},
        vol.Optional("outdoor_from", default=-25.0): _OUTDOOR,
        vol.Optional("outdoor_to", default=20.0): _OUTDOOR,
        vol.Optional("step", default=0.5): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=10)),
    }
)
@callback
def ws_curve(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """The curve's points for the settings in use, or for draft values given in the message —
    a preview only: nothing is saved. The problems are the settings' own checks, by their
    translation keys; ``invalid_curve`` where the values cannot make a curve at all."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_running(connection, msg)
        return
    control = coordinator.config.control
    loop = control.loop.control
    if not control.configured or loop.on_off:
        connection.send_error(msg["id"], NO_CURVE, "control does not set the water")
        return
    try:
        curve = replace(loop.curve, **{key: msg[key] for key in CURVE_KEYS if key in msg})
        limits = replace(loop.limits, **{key: msg[key] for key in LIMIT_KEYS if key in msg})
    except ValueError:
        connection.send_result(msg["id"], {"points": [], "problems": [INVALID_CURVE]})
        return
    problems = [
        key
        for _field, key in curve_problems(
            curve.design_flow, curve.design_outdoor, curve.room, limits.hard_min, limits.hard_max
        )
    ]
    if lowest_above_max(replace(loop, curve=curve, limits=limits)):
        problems.append("hard_min_above_max")
    try:
        points = curve_points(
            curve,
            limits,
            loop.circuit_max,
            loop.boiler_max,
            msg["outdoor_from"],
            msg["outdoor_to"],
            step=msg["step"],
        )
    except ValueError as err:
        connection.send_error(msg["id"], INVALID_RANGE, str(err))
        return
    connection.send_result(
        msg["id"], {"points": [list(point) for point in points], "problems": problems}
    )


@websocket_command(
    {vol.Required("type"): f"{DOMAIN}/days", vol.Optional("since"): vol.Coerce(float)}
)
@callback
def ws_days(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """The daily summaries kept (a year at most), oldest first, in their stored form; ``since``:
    only the days that start at or after it (a Unix time). With them, the last 12 weeks' gas per
    degree-day as ``core.weekly`` reckons it, and the energy signature as ``core.signature``
    fits it through the heating threshold in use (I10.7), both over every day kept."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_running(connection, msg)
        return
    since = msg.get("since")
    days = sorted(coordinator.daily.values(), key=lambda day: day.start)
    data = coordinator.data
    threshold = (
        None if data is None else data.parameters.get(ParameterKey.HEATING_THRESHOLD).effective()
    )
    signature = energy_signature(days, None if threshold is None else threshold.value)
    connection.send_result(
        msg["id"],
        {
            "days": [day.to_dict() for day in days if since is None or day.start >= since],
            "weeks": [asdict(week) for week in weekly_use(days, WEEKS_SHOWN)],
            "signature": _signature(signature),
            "gas_unit": _meter_unit(hass, coordinator),
        },
    )


def _meter_unit(hass: HomeAssistant, coordinator: SmartBoilerCoordinator) -> str | None:
    """The gas meter's unit as its entity reports it now; ``None`` without a meter — the days'
    gas is then estimated in the unit of the boiler's gas figures (P-75)."""
    entity = coordinator.config.signals.get(Signal.GAS_METER)
    state = hass.states.get(entity) if entity else None
    unit = state.attributes.get("unit_of_measurement") if state is not None else None
    return str(unit) if unit else None


def _signature(signature: Signature) -> dict[str, Any]:
    def fit(found: SignatureFit) -> dict[str, Any]:
        line = found.line
        return {
            "line": None if line is None else {**asdict(line), "balance": line.balance},
            "reason": None if found.reason is None else found.reason.value,
        }

    compared = signature.comparison
    return {
        "days": [asdict(day) for day in signature.days],
        "observing": fit(signature.observing),
        "control": fit(signature.control),
        "comparison": None if compared is None else asdict(compared),
        # What a line needs, so the page says why there is none (``core.building``'s rules).
        "min_days": MIN_FIT_DAYS,
        "min_spread_k": MIN_OUTDOOR_SPREAD_K,
    }


@websocket_command({vol.Required("type"): f"{DOMAIN}/burns"})
@callback
def ws_burns(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """The burns of the monitor's last analysis, as it classified them — heating, hot water or
    unknown — with when that analysis ran: the page draws the monitor's own burns and judges
    none itself. None before the first analysis."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_running(connection, msg)
        return
    analysed = coordinator.analysis
    if analysed is None:
        connection.send_result(msg["id"], {"at": None, "burns": []})
        return
    connection.send_result(
        msg["id"],
        {
            "at": analysed.at,
            "burns": [
                {
                    "start": classified.burn.start,
                    "end": classified.burn.end,
                    "kind": classified.kind.value,
                    "start_seen": classified.burn.start_seen,
                    "end_seen": classified.burn.end_seen,
                }
                for classified in analysed.day.burns
            ],
        },
    )


@websocket_command(
    {vol.Required("type"): f"{DOMAIN}/journal", vol.Optional("since"): vol.Coerce(float)}
)
@callback
def ws_journal(hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]) -> None:
    """The journal, oldest first — from ``since`` on where it is given — with how long and how
    many entries it keeps (I10.6)."""
    coordinator = _coordinator(hass)
    if coordinator is None or coordinator.journal is None:
        _not_running(connection, msg)
        return
    since = msg.get("since")
    entries = coordinator.journal.entries
    connection.send_result(
        msg["id"],
        {
            "entries": [
                entry_to_stored(entry) for entry in entries if since is None or entry.at >= since
            ],
            "days": JOURNAL_DAYS,
            "max": JOURNAL_MAX,
        },
    )


# What the page may change of the curve, as the settings' "Heating curve" form names it; the
# offset only where the entry's level shows it.
SAVE_KEYS = ("design_outdoor", "design_flow", "offset")
CURVE_STEP = "control_curve"
NOT_AVAILABLE = "not_available"


def _form_values(schema: Any) -> dict[str, Any]:
    """The values a settings form shows, filled from the stored options: each field's default,
    or, where it has none, its suggested value — the exponent and the fallback setpoint are shown
    so, and a save without them would drop what is stored (J4 I10.10, F16)."""
    values: dict[str, Any] = {}
    for marker in schema.schema:
        value: Any = None
        default = getattr(marker, "default", None)
        if callable(default):
            value = default()
        if value is vol.UNDEFINED or value is None or repr(value) == "...":
            value = (getattr(marker, "description", None) or {}).get("suggested_value")
        if value is not None:
            values[str(marker)] = value
    return values


@websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/curve/save",
        vol.Optional("design_outdoor"): vol.Coerce(float),
        vol.Optional("design_flow"): vol.Coerce(float),
        vol.Optional("offset"): vol.Coerce(float),
    }
)
@require_admin
@async_response
async def ws_curve_save(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Save the curve the page previewed — an administrator only — through the plugin's own
    settings: their "Heating curve" form with the stored values and these changes, then "Save
    and finish". Every check is the settings' own and the save is theirs, with its one reload.
    A form that refuses answers its errors by their translation keys; a save the settings would
    take the user through first (a confirmation, another section) is not made — the answer names
    the step, for the user to finish in the settings. Nothing is changed then."""
    coordinator = _coordinator(hass)
    if coordinator is None:
        _not_running(connection, msg)
        return
    changes = {key: msg[key] for key in SAVE_KEYS if key in msg}
    options = hass.config_entries.options
    flow = await options.async_init(coordinator.config_entry.entry_id)
    flow_id = flow["flow_id"]
    try:
        try:
            form = await options.async_configure(flow_id, {"next_step_id": CURVE_STEP})
        except InvalidData, UnknownStep:  # the curve's item is not on the menu
            form = None
        schema = form.get("data_schema") if form else None
        if schema is None or form is None or form.get("step_id") != CURVE_STEP:
            connection.send_error(msg["id"], NOT_AVAILABLE, "the curve cannot be changed now")
            return
        if "offset" in changes and "offset" not in {str(m) for m in schema.schema}:
            refused = {"saved": False, "errors": {"offset": "offset_advanced"}}
            connection.send_result(msg["id"], refused)
            return
        try:
            answer = await options.async_configure(flow_id, {**_form_values(schema), **changes})
        except InvalidData as err:  # outside a field's bounds, as the form's own number box
            field = str(err.path[0]) if err.path else "base"
            refused = {"saved": False, "errors": {field: "out_of_range"}}
            connection.send_result(msg["id"], refused)
            return
        if answer.get("type") is FlowResultType.FORM and answer.get("step_id") == CURVE_STEP:
            errors = dict(answer.get("errors") or {})
            connection.send_result(msg["id"], {"saved": False, "errors": errors})
            return
        journal = coordinator.journal
        if journal is not None:  # the save the settings report next is the page's (I10.6)
            journal.note_page_save(["curve"])
        saved = await options.async_configure(flow_id, {"next_step_id": "save"})
        if saved.get("type") is FlowResultType.CREATE_ENTRY:
            connection.send_result(msg["id"], {"saved": True, "errors": {}})
            return
        if journal is not None:
            journal.forget_page_save()
        connection.send_result(
            msg["id"],
            {"saved": False, "errors": {"base": "needs_settings"}, "step": saved.get("step_id")},
        )
    finally:
        with suppress(UnknownFlow):  # a save finishes the flow itself
            options.async_abort(flow_id)
