"""Config flow and options flow.

The level (simple or advanced) changes which fields are shown, never how the plugin behaves:
a field that is not shown keeps its cautious default. Every step reads and writes one part of
the options dictionary that ``config.EntryConfig`` interprets.
"""

from __future__ import annotations

import copy
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .config import ConfigError, EntryConfig
from .const import (
    BOILER,
    BUILDING,
    CIRCUITS,
    DOMAIN,
    LEVEL,
    LEVEL_ADVANCED,
    LEVEL_SIMPLE,
    MONITOR,
    PARAMETERS,
    REFERENCE_ROOM,
    SIGNALS,
    VT_DOMAIN,
    WEATHER,
    ZONES,
)
from .core.building import InsulationClass, ThermalMass
from .core.foreign_heat import SourceKind
from .core.installation import BoilerClass, CircuitControl, DhwType, EmitterType
from .core.metrics import ModulationScale
from .core.reference_room import Strategy

# --- field definitions ----------------------------------------------------------------------

_BINARY = {"domain": "binary_sensor"}
_TEMPERATURE = {"domain": "sensor", "device_class": "temperature"}

# signal -> (entity filter, shown at the simple level)
SIGNAL_FIELDS: dict[str, tuple[dict[str, Any], bool]] = {
    "flame": (_BINARY, True),
    "flow": (_TEMPERATURE, True),
    "return": (_TEMPERATURE, True),
    "modulation": ({"domain": "sensor"}, True),
    "dhw_active": (_BINARY, True),
    "pressure": ({"domain": "sensor", "device_class": "pressure"}, True),
    "outdoor": (_TEMPERATURE, True),
    "ch_setpoint": ({"domain": ["sensor", "number"]}, False),
    "ch_active": (_BINARY, False),
    "pump_running": (_BINARY, False),
    "flue_gas": (_TEMPERATURE, False),
    "gas_meter": ({"domain": "sensor", "device_class": ["gas", "energy"]}, False),
    "room_setpoint": (_TEMPERATURE, False),
    "room_temperature": (_TEMPERATURE, False),
}
REQUIRED_FIELDS = ("flame", "flow")


def _entity(filter_: dict[str, Any], multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(filter=[filter_], multiple=multiple)  # type: ignore[typeddict-item]
    )


def _select(key: str, options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, translation_key=key, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _number(
    low: float, high: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=low, max=high, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _optional(key: str, current: dict[str, Any]) -> vol.Optional:
    value = current.get(key)
    return vol.Optional(key, description={"suggested_value": value} if value is not None else None)


def _advanced(options: dict[str, Any]) -> bool:
    return options.get(LEVEL) == LEVEL_ADVANCED


# --- schemas ----------------------------------------------------------------------------------


def user_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("name", default=current.get("name", "Boiler")): str,
            vol.Required(LEVEL, default=current.get(LEVEL, LEVEL_SIMPLE)): _select(
                "level", [LEVEL_SIMPLE, LEVEL_ADVANCED]
            ),
        }
    )


def signals_schema(options: dict[str, Any]) -> vol.Schema:
    current = {**options.get(SIGNALS, {}), WEATHER: options.get(WEATHER)}
    fields: dict[Any, Any] = {}
    for key, (filter_, simple) in SIGNAL_FIELDS.items():
        if not simple and not _advanced(options):
            continue
        marker = (
            vol.Required(key, default=current[key])
            if key in REQUIRED_FIELDS and current.get(key)
            else vol.Required(key)
            if key in REQUIRED_FIELDS
            else _optional(key, current)
        )
        fields[marker] = _entity(filter_)
    fields[_optional(WEATHER, current)] = _entity({"domain": "weather"})
    return vol.Schema(fields)


def boiler_schema(options: dict[str, Any]) -> vol.Schema:
    boiler = options.get(BOILER, {})
    params = options.get(PARAMETERS, {})
    current = {**boiler, **params}
    fields: dict[Any, Any] = {
        vol.Required("class", default=boiler.get("class", BoilerClass.READ_ONLY.value)): _select(
            "boiler_class", [c.value for c in BoilerClass]
        ),
        vol.Required("dhw", default=boiler.get("dhw", DhwType.NONE.value)): _select(
            "dhw_type", [d.value for d in DhwType]
        ),
        vol.Required(
            "condensing", default=boiler.get("condensing", True)
        ): selector.BooleanSelector(),
        _optional("boiler_min_power", current): _number(0.3, 200, 0.1, "kW"),
        _optional("boiler_max_power", current): _number(1, 500, 0.1, "kW"),
    }
    if _advanced(options):
        fields.update(
            {
                _optional("max_ch_setpoint", current): _number(20, 95, 1, "°C"),
                _optional("gas_at_min_power", current): _number(0, 200, 0.01),
                _optional("gas_at_max_power", current): _number(0, 500, 0.01),
                vol.Required(
                    "modulation_scale",
                    default=boiler.get("modulation_scale", ModulationScale.RANGE.value),
                ): _select("modulation_scale", [m.value for m in ModulationScale]),
                vol.Required(
                    "shared_return", default=boiler.get("shared_return", False)
                ): selector.BooleanSelector(),
            }
        )
    return vol.Schema(fields)


def circuit_schema(options: dict[str, Any], current: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(
            "control", default=current.get("control", CircuitControl.UNMIXED_SHARED.value)
        ): _select("circuit_control", [c.value for c in CircuitControl]),
        _optional("max_flow", current): _number(20, 90, 1, "°C"),
        _optional("fixed_temperature", current): _number(20, 70, 1, "°C"),
    }
    if _advanced(options):
        fields[_optional("flow_entity", current)] = _entity(_TEMPERATURE)
        fields[vol.Required("add_another", default=False)] = selector.BooleanSelector()
    return vol.Schema(fields)


def zones_schema(options: dict[str, Any]) -> vol.Schema:
    current = [z["entity_id"] for z in options.get(ZONES, [])]
    return vol.Schema(
        {
            vol.Optional("zones", default=current): _entity(
                {"domain": "climate", "integration": VT_DOMAIN}, multiple=True
            )
        }
    )


def zone_schema(options: dict[str, Any], current: dict[str, Any]) -> vol.Schema:
    circuits = [c["id"] for c in options.get(CIRCUITS, [])] or ["main"]
    fields: dict[Any, Any] = {}
    if len(circuits) > 1:
        fields[vol.Required("circuit", default=current.get("circuit", circuits[0]))] = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=circuits, mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
        )
    fields[vol.Required("emitter", default=current.get("emitter", EmitterType.RADIATOR.value))] = (
        _select("emitter", [e.value for e in EmitterType])
    )
    sources = [s["entity_id"] for s in current.get("foreign_heat", [])]
    fields[vol.Optional("foreign_heat", default=sources)] = _entity(
        {"domain": ["switch", "binary_sensor", "sensor"]}, multiple=True
    )
    if _advanced(options):
        fields[_optional("reference_output_w", current)] = _number(50, 20000, 10, "W")
        fields[_optional("exponent", current)] = _number(1.0, 2.0, 0.01)
        thresholds = {
            s["kind"]: s.get("threshold")
            for s in current.get("foreign_heat", [])
            if s.get("threshold")
        }
        fields[_optional("power_threshold", {"power_threshold": thresholds.get("power")})] = (
            _number(1, 10000, 1, "W")
        )
        fields[
            _optional(
                "temperature_threshold", {"temperature_threshold": thresholds.get("temperature")}
            )
        ] = _number(20, 300, 1, "°C")
    return vol.Schema(fields)


def building_schema(options: dict[str, Any]) -> vol.Schema:
    building = options.get(BUILDING, {})
    params = options.get(PARAMETERS, {})
    fields: dict[Any, Any] = {
        _optional("floor_area", building): _number(10, 5000, 1, "m²"),
        _optional("insulation", building): _select(
            "insulation", [i.value for i in InsulationClass]
        ),
        _optional("thermal_mass", building): _select(
            "thermal_mass", [m.value for m in ThermalMass]
        ),
    }
    if _advanced(options):
        fields.update(
            {
                _optional("design_load_kw", building): _number(0.5, 200, 0.1, "kW"),
                _optional("loss_coefficient", params): _number(0.01, 5, 0.001, "kW/K"),
                _optional("heating_threshold", params): _number(5, 22, 0.5, "°C"),
                _optional("design_outdoor", params): _number(-45, 10, 1, "°C"),
            }
        )
    return vol.Schema(fields)


def reference_schema(options: dict[str, Any]) -> vol.Schema:
    reference = options.get(REFERENCE_ROOM, {})
    zones = [z["entity_id"] for z in options.get(ZONES, [])]
    strategies = [Strategy.LARGEST_DEFICIT.value, Strategy.AVERAGE.value]
    if zones:
        strategies.insert(1, Strategy.CHOSEN_ZONE.value)
    fields: dict[Any, Any] = {
        vol.Required(
            "strategy", default=reference.get("strategy", Strategy.LARGEST_DEFICIT.value)
        ): _select("strategy", strategies),
    }
    if zones:
        fields[_optional("zone", reference)] = _entity(
            {"domain": "climate", "integration": VT_DOMAIN}
        )
    if _advanced(options):
        fields[vol.Required("switch_margin", default=reference.get("switch_margin", 0.3))] = (
            _number(0.1, 3.0, 0.1, "K")
        )
    return vol.Schema(fields)


def monitor_schema(options: dict[str, Any]) -> vol.Schema:
    monitor = options.get(MONITOR, {})
    return vol.Schema(
        {
            vol.Required("condensing_return", default=monitor.get("condensing_return", 55.0)): (
                _number(40, 65, 0.5, "°C")
            ),
            vol.Required("short_burn_min", default=monitor.get("short_burn_min", 10.0)): _number(
                1, 60, 1, "min"
            ),
            vol.Required("monitoring_days", default=monitor.get("monitoring_days", 7.0)): _number(
                7, 60, 1, "d"
            ),
            vol.Required("near_room_k", default=monitor.get("near_room_k", 3.0)): _number(
                1, 10, 0.5, "K"
            ),
            vol.Required(
                "foreign_heat_hold_min", default=monitor.get("foreign_heat_hold_min", 60.0)
            ): _number(0, 720, 5, "min"),
        }
    )


# --- applying user input ----------------------------------------------------------------------

BOILER_KEYS = ("class", "dhw", "condensing", "modulation_scale", "shared_return")
BOILER_PARAMETER_KEYS = (
    "boiler_min_power",
    "boiler_max_power",
    "max_ch_setpoint",
    "gas_at_min_power",
    "gas_at_max_power",
)
BUILDING_KEYS = ("floor_area", "insulation", "thermal_mass", "design_load_kw")
BUILDING_PARAMETER_KEYS = ("loss_coefficient", "heating_threshold", "design_outdoor")


def apply_signals(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    signals = dict(options.get(SIGNALS, {}))
    for key, (_filter, simple) in SIGNAL_FIELDS.items():
        if simple or _advanced(options):
            if user_input.get(key):
                signals[key] = user_input[key]
            else:
                signals.pop(key, None)
    options[SIGNALS] = signals
    options[WEATHER] = user_input.get(WEATHER) or None


def apply_boiler(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    boiler = dict(options.get(BOILER, {}))
    boiler.update({k: user_input[k] for k in BOILER_KEYS if k in user_input})
    options[BOILER] = boiler
    _apply_parameters(options, user_input, BOILER_PARAMETER_KEYS)


def apply_building(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    building = dict(options.get(BUILDING, {}))
    for key in BUILDING_KEYS:
        if key in user_input and user_input[key] not in (None, ""):
            building[key] = user_input[key]
        elif _advanced(options) or key != "design_load_kw":
            building.pop(key, None)
    options[BUILDING] = building
    _apply_parameters(options, user_input, BUILDING_PARAMETER_KEYS)


def _apply_parameters(
    options: dict[str, Any], user_input: dict[str, Any], keys: tuple[str, ...]
) -> None:
    params = dict(options.get(PARAMETERS, {}))
    shown_advanced = _advanced(options)
    for key in keys:
        if key in user_input and user_input[key] not in (None, ""):
            params[key] = user_input[key]
        elif key in ("boiler_min_power", "boiler_max_power") or shown_advanced:
            params.pop(key, None)
    options[PARAMETERS] = params


def circuit_from_input(user_input: dict[str, Any], circuit_id: str) -> dict[str, Any]:
    circuit: dict[str, Any] = {"id": circuit_id, "control": user_input["control"]}
    for key in ("max_flow", "fixed_temperature", "flow_entity"):
        if user_input.get(key) not in (None, ""):
            circuit[key] = user_input[key]
    return circuit


def source_kind(hass_state_domain: str, device_class: str | None) -> SourceKind | None:
    if hass_state_domain == "switch":
        return SourceKind.SWITCH
    if hass_state_domain == "binary_sensor":
        return SourceKind.BINARY
    if device_class == "power":
        return SourceKind.POWER
    if device_class == "temperature":
        return SourceKind.TEMPERATURE
    return None


def apply_monitor(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    options[MONITOR] = dict(user_input)


def restore_advanced_defaults(options: dict[str, Any]) -> None:
    """Drop every value only the advanced level shows, so its default applies again."""
    signals = options.get(SIGNALS, {})
    for key, (_filter, simple) in SIGNAL_FIELDS.items():
        if not simple:
            signals.pop(key, None)
    boiler = options.get(BOILER, {})
    for key in ("modulation_scale", "shared_return"):
        boiler.pop(key, None)
    params = options.get(PARAMETERS, {})
    for key in (
        "max_ch_setpoint",
        "gas_at_min_power",
        "gas_at_max_power",
        *BUILDING_PARAMETER_KEYS,
    ):
        params.pop(key, None)
    options.get(BUILDING, {}).pop("design_load_kw", None)
    circuits = options.get(CIRCUITS, [])
    if circuits:
        first = {k: v for k, v in circuits[0].items() if k != "flow_entity"}
        options[CIRCUITS] = [first]
        first_id = first["id"]
        for zone in options.get(ZONES, []):
            zone["circuit"] = first_id
    for zone in options.get(ZONES, []):
        zone.pop("reference_output_w", None)
        zone.pop("exponent", None)
        for source in zone.get("foreign_heat", []):
            source.pop("threshold", None)
    options.get(REFERENCE_ROOM, {}).pop("switch_margin", None)
    options.pop(MONITOR, None)


ADVANCED_SIGNALS = tuple(key for key, (_f, simple) in SIGNAL_FIELDS.items() if not simple)


def has_hidden_advanced(options: dict[str, Any]) -> bool:
    """At the simple level: whether any setting only the advanced level shows is set."""
    if _advanced(options):
        return False
    params = options.get(PARAMETERS, {})
    circuits = options.get(CIRCUITS, [])
    zones = options.get(ZONES, [])
    return bool(
        any(key in options.get(SIGNALS, {}) for key in ADVANCED_SIGNALS)
        or any(key in options.get(BOILER, {}) for key in ("modulation_scale", "shared_return"))
        or any(
            key in params
            for key in (
                "max_ch_setpoint",
                "gas_at_min_power",
                "gas_at_max_power",
                *BUILDING_PARAMETER_KEYS,
            )
        )
        or "design_load_kw" in options.get(BUILDING, {})
        or len(circuits) > 1
        or any("flow_entity" in c for c in circuits)
        or any("reference_output_w" in z or "exponent" in z for z in zones)
        or any("threshold" in s for z in zones for s in z.get("foreign_heat", []))
        or "switch_margin" in options.get(REFERENCE_ROOM, {})
        or MONITOR in options
    )


def validate(options: dict[str, Any]) -> str | None:
    """A translation key of the first problem, or None."""
    try:
        EntryConfig.from_options(options)
    except ConfigError as err:
        return err.code
    return None


# --- flows ------------------------------------------------------------------------------------


class _Steps:
    """Steps shared by the config flow and the options flow."""

    options: dict[str, Any]
    _zone_queue: list[str]
    _zones_done: list[dict[str, Any]]
    _circuits_done: list[dict[str, Any]]

    def _next_after(self, step: str) -> str:
        raise NotImplementedError

    async def _goto(self, step: str) -> ConfigFlowResult:
        return await getattr(self, f"async_step_{step}")()

    async def async_step_signals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            apply_signals(self.options, user_input)
            return await self._goto(self._next_after("signals"))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="signals", data_schema=signals_schema(self.options), errors=errors
        )

    async def async_step_boiler(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            low, high = user_input.get("boiler_min_power"), user_input.get("boiler_max_power")
            if low is not None and high is not None and low >= high:
                errors["base"] = "min_power_not_below_max"
            else:
                apply_boiler(self.options, user_input)
                return await self._goto(self._next_after("boiler"))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="boiler", data_schema=boiler_schema(self.options), errors=errors
        )

    async def async_step_circuit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        index = len(self._circuits_done)
        existing = self.options.get(CIRCUITS, [])
        current = existing[index] if index < len(existing) else {}
        if user_input is not None:
            circuit = circuit_from_input(user_input, current.get("id", f"circuit_{index + 1}"))
            if index == 0 and not current:
                circuit["id"] = "main"
            if (
                circuit["control"] == CircuitControl.PASSIVE_FIXED
                and "fixed_temperature" not in circuit
            ):
                errors["fixed_temperature"] = "fixed_temperature_missing"
            else:
                self._circuits_done.append(circuit)
                if user_input.get("add_another"):
                    return await self.async_step_circuit()
                self.options[CIRCUITS] = self._circuits_done
                self._circuits_done = []
                return await self._goto(self._next_after("circuit"))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="circuit",
            data_schema=circuit_schema(self.options, current),
            errors=errors,
            description_placeholders={"number": str(index + 1)},
        )

    async def async_step_zones(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._zone_queue = list(user_input.get("zones", []))
            self._zones_done = []
            return await self.async_step_zone()
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="zones", data_schema=zones_schema(self.options)
        )

    async def async_step_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not self._zone_queue:
            self.options[ZONES] = self._zones_done
            return await self._goto(self._next_after("zones"))
        entity_id = self._zone_queue[0]
        previous = {z["entity_id"]: z for z in self.options.get(ZONES, [])}
        current = previous.get(entity_id, {})
        errors: dict[str, str] = {}
        if user_input is not None:
            zone: dict[str, Any] = {"entity_id": entity_id, "emitter": user_input["emitter"]}
            circuits = [c["id"] for c in self.options.get(CIRCUITS, [])] or ["main"]
            zone["circuit"] = user_input.get("circuit", circuits[0])
            for key in ("reference_output_w", "exponent"):
                if user_input.get(key) not in (None, ""):
                    zone[key] = user_input[key]
            sources = []
            for source_id in user_input.get("foreign_heat", []):
                state = self.hass.states.get(source_id)  # type: ignore[attr-defined]
                kind = source_kind(
                    source_id.split(".")[0],
                    state.attributes.get("device_class") if state is not None else None,
                )
                if kind is None:
                    errors["foreign_heat"] = "foreign_heat_unsupported"
                    break
                source: dict[str, Any] = {"entity_id": source_id, "kind": kind.value}
                threshold = user_input.get(f"{kind.value}_threshold")
                if threshold not in (None, ""):
                    source["threshold"] = threshold
                elif kind is SourceKind.TEMPERATURE:
                    errors["foreign_heat"] = "temperature_threshold_missing"
                    break
                sources.append(source)
            if not errors:
                zone["foreign_heat"] = sources
                self._zones_done.append(zone)
                self._zone_queue.pop(0)
                return await self.async_step_zone()
        name_state = self.hass.states.get(entity_id)  # type: ignore[attr-defined]
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="zone",
            data_schema=zone_schema(self.options, current),
            errors=errors,
            description_placeholders={"zone": name_state.name if name_state else entity_id},
        )

    async def async_step_building(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            apply_building(self.options, user_input)
            return await self._goto(self._next_after("building"))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="building", data_schema=building_schema(self.options)
        )

    async def async_step_reference(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            reference = {k: v for k, v in user_input.items() if v not in (None, "")}
            zones = [z["entity_id"] for z in self.options.get(ZONES, [])]
            if (
                reference.get("strategy") == Strategy.CHOSEN_ZONE
                and reference.get("zone") not in zones
            ):
                errors["zone"] = "reference_zone_unknown"
            else:
                if reference.get("strategy") != Strategy.CHOSEN_ZONE:
                    reference.pop("zone", None)
                self.options[REFERENCE_ROOM] = reference
                return await self._goto(self._next_after("reference"))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="reference", data_schema=reference_schema(self.options), errors=errors
        )

    async def async_step_monitor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            apply_monitor(self.options, user_input)
            return await self._goto(self._next_after("monitor"))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="monitor", data_schema=monitor_schema(self.options)
        )


class SmartBoilerConfigFlow(_Steps, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}
        self._title = "Boiler"
        self._zone_queue = []
        self._zones_done = []
        self._circuits_done = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SmartBoilerOptionsFlow()

    ORDER = ("signals", "boiler", "circuit", "zones", "building", "reference", "monitor", "finish")

    def _next_after(self, step: str) -> str:
        following = self.ORDER[self.ORDER.index(step) + 1]
        if following == "monitor" and not _advanced(self.options):
            return "finish"
        return following

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._title = user_input["name"]
            self.options[LEVEL] = user_input[LEVEL]
            return await self.async_step_signals()
        return self.async_show_form(step_id="user", data_schema=user_schema({}))

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        problem = validate(self.options)
        if problem is not None:
            return self.async_abort(reason=problem)
        return self.async_create_entry(title=self._title, data={}, options=self.options)


class SmartBoilerOptionsFlow(_Steps, OptionsFlow):
    """A menu of sections; each saves the options when done."""

    def __init__(self) -> None:
        self._zone_queue = []
        self._zones_done = []
        self._circuits_done = []
        self._options: dict[str, Any] | None = None

    @property
    def options(self) -> dict[str, Any]:  # type: ignore[override]
        if self._options is None:
            self._options = copy.deepcopy(dict(self.config_entry.options))
        return self._options

    def _next_after(self, step: str) -> str:
        return "save"

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["signals", "boiler", "circuit", "zones", "building", "reference"]
        if _advanced(self.options):
            menu.append("monitor")
        # At the simple level, say when hidden advanced settings are still active.
        menu.append("level_hidden" if has_hidden_advanced(self.options) else "level")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_level_hidden(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_level(user_input)

    async def async_step_level(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if user_input[LEVEL] == LEVEL_SIMPLE and user_input.get("restore_defaults"):
                restore_advanced_defaults(self.options)
            self.options[LEVEL] = user_input[LEVEL]
            return await self.async_step_save()
        schema = vol.Schema(
            {
                vol.Required(LEVEL, default=self.options.get(LEVEL, LEVEL_SIMPLE)): _select(
                    "level", [LEVEL_SIMPLE, LEVEL_ADVANCED]
                ),
                vol.Required("restore_defaults", default=False): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="level", data_schema=schema)

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        problem = validate(self.options)
        if problem is not None:
            return self.async_abort(reason=problem)
        return self.async_create_entry(data=self.options)
