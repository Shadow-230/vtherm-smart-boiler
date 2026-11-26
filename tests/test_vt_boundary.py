"""I12.13: no module of the integration reads VT's data outside ``vtherm_api``.

VT's data are VT's own entities — the climates of VT's integration and the sensors, binary
sensors and select it creates — and VT's config entries. What the plugin may read from Home
Assistant is none of them (``plan-0.2-i12.md``, second part): entities its own settings name
(the user picks them for the boiler's side: the signals, the write targets, the relay, the
weather, the gas meter, the helper VT's central boiler switches), the two devices of the user's
that VT names in ``entry_infos`` (the room thermometer, the window sensor), and Home Assistant's
information about integrations and entries (VT loaded or not).

A read cannot tell by itself whose entity it gets, so the guard pins every place that reads, and
says there whose entity it is:

1. Every read of a state, a state's history or changes, a config entry, an event or VT's
   ``hass.data`` sits in a function listed in ``READS``, with whose entity or entry it reads. A
   read anywhere else fails: whoever adds one adds it here, with its reason.
2. ``config_entries.async_entries`` always names a domain, and VT's only where the plugin asks
   whether VT is loaded.
3. A state's ``.attributes`` gives only Home Assistant's own attribute names (``HA_ATTRIBUTES``),
   read at once or through one local name: never an attribute VT adds to its climates.

TB-16 (``test_vtherm_names.py``) keeps VT's names in the two link modules; this guard keeps
VT's entities out of every module.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/vtherm_smart_boiler"

# Home Assistant's own attribute names, the only ones read from a state.
HA_ATTRIBUTES = frozenset(
    {
        "assumed_state",
        "device_class",
        "hvac_modes",
        "max",
        "min",
        "step",
        "supported_features",
        "temperature",  # a weather entity's
        "temperature_unit",  # a weather entity's
        "unit_of_measurement",
    }
)

# Where a state's attributes are read by a name not written out, or handed on whole: the
# function, and what it reads. A name written out is still checked there.
ATTRIBUTES_HANDED_ON = {
    ("transport/entities.py", "bounds_from_state.celsius"): "called with min and max only",
    ("forecasts.py", "ForecastRecorder.async_take"): (
        "the weather's units, to parse_forecast: temperature_unit, wind_speed_unit and "
        "precipitation_unit"
    ),
}

_USER = "an entity the user picks in the plugin's settings"
_RELAY = "the relay the user picks; the form refuses one of VT's (R2)"
_HELPER = "the helper VT's central boiler switches: the user's input_boolean (I12.8)"
_WRITE = "a write target or its read-back the user picks"
_OWN_ENTRY = "the plugin's own config entry, by its ID"

# (module, function) -> whose entity or entry the function reads.
READS: dict[tuple[str, str], str] = {
    # vtherm_link.py: VT's devices of the user's, VT loaded, VT's events (decision 8).
    ("vtherm_link.py", "VThermLink._device_state"): (
        "the room thermometer and window sensor VT names in entry_infos: the user's devices"
    ),
    ("vtherm_link.py", "VThermLink.capabilities"): (
        "VT loaded: the state of VT's config entries, nothing in them (gap 19)"
    ),
    ("vtherm_link.py", "VThermLink.start"): "VT's safety and window events (decision 8)",
    # feature_manager.py: finding VT's API without creating a bare one.
    ("feature_manager.py", "_stored_api"): "VT's API instance where VT keeps it: the API itself",
    ("feature_manager.py", "FeatureRegistration.start"): (
        "Home Assistant's signal of a changed entry and its component-loaded event: VT's "
        "entries' domain and state only, to register with a new API"
    ),
    # __init__.py
    ("__init__.py", "_follow_renames"): _OWN_ENTRY,
    ("__init__.py", "_follow_once_set_up"): "Home Assistant's component-loaded event",
    # binary_sensor.py
    ("binary_sensor.py", "ConnectionSensor.extra_state_attributes"): _RELAY,
    # config_flow.py
    ("config_flow.py", "entity_suitable"): (
        "the device class of the entity picked in a boiler field: the user's pick — no field "
        "refuses one of VT's sensors, only the relay one of VT's climates"
    ),
    ("config_flow.py", "relay_entity_error"): (
        "the relay the user picks, its hvac_modes read only after the registry refused VT's (R2)"
    ),
    ("config_flow.py", "gateways_set_up"): "the OpenTherm Gateway integration's entries",
    ("config_flow.py", "gateway_entities"): "the OpenTherm Gateway integration's entries",
    ("config_flow.py", "vt_helper_error"): _HELPER + ", whether it exists",
    ("config_flow.py", "mqtt_set_up"): "the MQTT integration's entries",
    ("config_flow.py", "_Steps.async_step_signals"): "the modulation entity the user picks",
    # control.py
    ("control.py", "ControlUnit._vt_boiler_blockers"): _HELPER + ", whether it exists",
    ("control.py", "ControlUnit._vt_heat"): _HELPER,
    ("control.py", "ControlUnit._follow_vt_boiler"): (
        _HELPER + "; VT's central boiler event (decision 1)"
    ),
    ("control.py", "ControlUnit._relay_blockers"): _RELAY,
    ("control.py", "ControlUnit._integration_missing"): (
        "the OpenTherm Gateway and MQTT integrations' entries"
    ),
    ("control.py", "ControlUnit._target_ready"): _WRITE,
    ("control.py", "ControlUnit._note_step_aside"): _RELAY,
    ("control.py", "ControlUnit._assumed"): _WRITE,
    ("control.py", "ControlUnit._watch_targets"): _WRITE,
    ("control.py", "ControlUnit._evaluate"): _WRITE,
    ("control.py", "ControlUnit._judge_two_valued"): _WRITE,
    ("control.py", "ControlUnit._returned"): _WRITE,
    ("control.py", "ControlUnit._changed_at"): _WRITE,
    ("control.py", "ControlUnit._watch_external"): _WRITE,
    ("control.py", "ControlUnit._hand_back_state_shown"): _WRITE,
    ("control.py", "ControlUnit._track_outages"): _WRITE + ", the signals and the restart one",
    ("control.py", "ControlUnit._relay_name"): _RELAY,
    ("control.py", "ControlUnit._relay_seen"): _RELAY,
    ("control.py", "ControlUnit._relay_seen_quietly"): _RELAY,
    # coordinator.py: the watched entities (``EntryConfig.watched_entities``) and the helper,
    # never VT's climates (I12.7b, I12.11).
    ("coordinator.py", "SmartBoilerCoordinator.async_start"): (
        "the watched entities and the helper: their states now and their changes"
    ),
    ("coordinator.py", "SmartBoilerCoordinator._async_fill_days.read"): (
        "the recorder's states of _recorded_entities: the watched entities, the helper, the "
        "plugin's own control-state sensor"
    ),
    ("coordinator.py", "SmartBoilerCoordinator._async_backfill.read"): (
        "the recorder's states of _recorded_entities, as above"
    ),
    ("coordinator.py", "_significant_states"): "the recorder's history query, as above",
    ("coordinator.py", "SmartBoilerCoordinator._relay_reachable"): _RELAY,
    ("coordinator.py", "SmartBoilerCoordinator._observe_rhythms"): "the weather the user picks",
    ("coordinator.py", "SmartBoilerCoordinator._weather_known"): "the weather the user picks",
    ("coordinator.py", "SmartBoilerCoordinator._entity_name"): "a boiler signal the user picks",
    ("coordinator.py", "_first_start"): _OWN_ENTRY,
    # the others
    ("diagnostics.py", "_Redactor._is_entity"): (
        "whether a value is an entity, to redact it: the registry first, so a room of VT's is "
        "found there and its state never looked at"
    ),
    ("forecasts.py", "ForecastRecorder.async_take"): "the weather the user picks",
    ("journal.py", "Journal.async_follow"): "Home Assistant's stop event",
    ("modulation_cap.py", "CapUnit._read_back"): _WRITE + ": the cap's number entity (I13.7)",
    ("repairs.py", "entry_busy"): _OWN_ENTRY,
    ("repairs.py", "async_release"): _OWN_ENTRY,
    ("repairs.py", "_async_release_stored"): _OWN_ENTRY,
    ("sensor.py", "_gas_unit"): "the gas meter the user picks",
    ("transport/entities.py", "EntityTransport.reading"): "a boiler signal the user picks",
    ("transport/entities.py", "read_temperature"): "a water temperature the user picks",
    ("transport/entities.py", "read_on_off"): _USER,
    ("transport/entities.py", "read_weather_temperature"): "the weather the user picks",
    ("transport/entities.py", "read_bounds"): _WRITE,
    ("transport/entities.py", "temperature_unit_of"): _USER,
    ("transport/entities.py", "read_grid"): _WRITE,
    ("transport/writers.py", "_ServiceWriter._check_target"): _WRITE,
    ("transport/writers.py", "EntityWriter.hand_back"): _WRITE,
    ("transport/writers.py", "EntityWriter._source"): _WRITE,
    ("transport/writers.py", "EntityWriter._heating_on_once"): _WRITE,
    ("transport/writers.py", "_GatewayWriter._require_connected"): "the gateway's entity",
    ("transport/writers.py", "_GatewayWriter._read_back_now"): "the gateway's read-back entity",
    ("transport/writers.py", "RelayWriter.hand_back"): _RELAY,
    ("websocket_api.py", "_coordinator"): "the plugin's own config entries",
    ("websocket_api.py", "_meter_unit"): "the gas meter the user picks",
}

# Reads of VT's data the guard finds, reported rather than hidden in READS. Empty: the one found
# at I12.13 (the relay form read a VT climate's modes before refusing it) was fixed there.
FOUND: dict[tuple[str, str], str] = {}

# Where ``config_entries.async_entries`` may take VT's domain: whether VT is loaded.
VT_ENTRIES = {("vtherm_link.py", "VThermLink.capabilities")}

_STATE_READS = frozenset({"get", "async_all", "async_entity_ids", "async_entity_ids_count"})
_ENTRY_READS = frozenset(
    {"async_entries", "async_get_entry", "async_loaded_entries", "async_entry_for_domain_unique_id"}
)
_RECORDER_READS = frozenset(
    {"get_significant_states", "state_changes_during_period", "get_last_state_changes"}
)
_FOLLOWS = frozenset({"async_track_state_change_event", "SIGNAL_CONFIG_ENTRY_CHANGED"})
_VT_DOMAIN = ("VT_DOMAIN", "versatile_thermostat")


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _functions(tree: ast.Module) -> Iterator[tuple[str, ast.AST]]:
    """Each function with its qualified name (``Class.method``, ``outer.inner``); the module's
    own code as ``<module>``."""

    def walk(node: ast.AST, prefix: str) -> Iterator[tuple[str, ast.AST]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name = f"{prefix}{child.name}"
                yield name, child
                yield from walk(child, f"{name}.")
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{child.name}.")
            else:  # a function defined inside a loop, a branch, a ``with``
                yield from walk(child, prefix)

    yield "<module>", tree
    yield from walk(tree, "")


def _own_nodes(function: ast.AST) -> Iterator[ast.AST]:
    """The nodes of a function, not of the functions or classes defined in it."""
    for child in ast.iter_child_nodes(function):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        yield child
        yield from _own_nodes(child)


def _is_vt_domain(node: ast.AST | None) -> bool:
    return (isinstance(node, ast.Name) and node.id == _VT_DOMAIN[0]) or (
        isinstance(node, ast.Constant) and node.value == _VT_DOMAIN[1]
    )


def _read_kind(node: ast.AST) -> str | None:
    """What kind of read a node is, if any."""
    if isinstance(node, ast.Attribute):
        owner = node.value.attr if isinstance(node.value, ast.Attribute) else None
        if owner == "states" and node.attr in _STATE_READS:
            return "a state"
        if owner == "config_entries" and node.attr in _ENTRY_READS:
            return "a config entry"
        if owner == "bus" and node.attr in ("async_listen", "async_listen_once"):
            return "an event"
        if node.attr in _RECORDER_READS or node.attr in _FOLLOWS:
            return "a history or a change"
    if isinstance(node, ast.Name) and (node.id in _RECORDER_READS or node.id in _FOLLOWS):
        return "a history or a change"
    if isinstance(node, ast.Call) and any(k.arg == "entity_ids" for k in node.keywords):
        return "a history or a change"
    # VT's own ``hass.data``: ``hass.data[VT_DOMAIN]``, ``hass.data.get(VT_DOMAIN)``.
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "data"
        and _is_vt_domain(node.slice)
    ):
        return "VT's hass.data"
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "data"
        and node.args
        and _is_vt_domain(node.args[0])
    ):
        return "VT's hass.data"
    return None


def _key(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> tuple[bool, object]:
    """How an ``.attributes`` mapping (or a name holding one) is read at ``node``:
    ``(True, key)`` for ``.get(key)`` or ``[key]`` (``key`` ``None`` when not a constant),
    ``(False, None)`` for anything else."""
    parent = parents.get(node)
    if isinstance(parent, ast.Subscript) and parent.value is node:
        key = parent.slice
        return True, key.value if isinstance(key, ast.Constant) else None
    if (
        isinstance(parent, ast.Attribute)
        and parent.attr == "get"
        and isinstance(call := parents.get(parent), ast.Call)
        and call.func is parent
        and call.args
    ):
        key = call.args[0]
        return True, key.value if isinstance(key, ast.Constant) else None
    return False, None


def _attribute_problems(
    module: str, name: str, function: ast.AST, parents: Mapping[ast.AST, ast.AST]
) -> Iterator[str]:
    own = list(_own_nodes(function))
    aliases: set[str] = set()
    reads: list[tuple[int, tuple[bool, object]]] = []
    for node in own:
        if not (isinstance(node, ast.Attribute) and node.attr == "attributes"):
            continue
        parent = parents.get(node)
        if (
            isinstance(parent, ast.Assign)
            and len(parent.targets) == 1
            and isinstance(parent.targets[0], ast.Name)
        ):
            aliases.add(parent.targets[0].id)
            continue
        reads.append((node.lineno, _key(node, parents)))
    for node in own:
        if isinstance(node, ast.Name) and node.id in aliases and isinstance(node.ctx, ast.Load):
            reads.append((node.lineno, _key(node, parents)))
    handed_on = (module, name) in ATTRIBUTES_HANDED_ON
    for line, (keyed, key) in reads:
        if not keyed and not handed_on:
            yield f"{module}:{line} {name}: a state's attributes used other than by one name"
        elif keyed and key is None and not handed_on:
            yield f"{module}:{line} {name}: a state's attribute read by a name not written out"
        elif key is not None and key not in HA_ATTRIBUTES:
            yield f"{module}:{line} {name}: reads the attribute {key!r}, not Home Assistant's"


def _entries_problems(
    module: str, name: str, function: ast.AST, parents: Mapping[ast.AST, ast.AST]
) -> Iterator[str]:
    own = list(_own_nodes(function))
    aliases: set[str] = set()
    for node in own:
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "async_entries"
            and isinstance(parent := parents.get(node), ast.Assign)
            and isinstance(parent.targets[0], ast.Name)
        ):
            aliases.add(parent.targets[0].id)
    for node in own:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            (isinstance(func, ast.Attribute) and func.attr == "async_entries")
            or (isinstance(func, ast.Name) and func.id in aliases)
        ):
            continue
        domain = node.args[0] if node.args else None
        domain = next((k.value for k in node.keywords if k.arg == "domain"), domain)
        if domain is None:
            yield f"{module}:{node.lineno} {name}: every config entry, VT's among them"
        elif _is_vt_domain(domain) and (module, name) not in VT_ENTRIES:
            yield f"{module}:{node.lineno} {name}: VT's config entries"


def violations(source: str, module: str, allowed: Mapping[tuple[str, str], str]) -> list[str]:
    """What breaks the three rules in one module's source; ``module`` its path in the package."""
    tree = ast.parse(source)
    parents = _parents(tree)
    found: list[str] = []
    for name, function in _functions(tree):
        for node in _own_nodes(function):
            kind = _read_kind(node)
            if kind is not None and (module, name) not in allowed:
                found.append(f"{module}:{node.lineno} {name}: reads {kind}, not listed in READS")
        found.extend(_attribute_problems(module, name, function, parents))
        found.extend(_entries_problems(module, name, function, parents))
    return found


def _modules() -> list[tuple[str, str]]:
    return [
        (path.relative_to(COMPONENT).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(COMPONENT.rglob("*.py"))
    ]


def _reading_functions(source: str) -> set[str]:
    tree = ast.parse(source)
    return {
        name
        for name, function in _functions(tree)
        if any(_read_kind(node) is not None for node in _own_nodes(function))
    }


def test_no_module_reads_vt_data_outside_the_api() -> None:
    """The three rules hold over every module of the integration, ``core/`` included."""
    allowed = {**READS, **FOUND}
    found = [v for module, source in _modules() for v in violations(source, module, allowed)]
    assert found == []


def test_every_listed_read_is_still_there() -> None:
    """The lists stay exact: a function listed reads something, and one gone leaves them."""
    reading = {
        (module, name) for module, source in _modules() for name in _reading_functions(source)
    }
    stale = sorted(set(READS) - reading) + sorted(set(FOUND) - reading)
    assert stale == []
    assert all((module, name) in READS for module, name in VT_ENTRIES)
    assert not set(READS) & set(FOUND)


@pytest.mark.parametrize(
    ("source", "module", "expected"),
    [
        # A room's thermostat read from its climate, in a module that never reads.
        (
            "def on(hass, thermostat):\n    return hass.states.get(thermostat.entity_id).state\n",
            "sensor.py",
            "sensor.py:2 on: reads a state, not listed in READS",
        ),
        # In the link module too, outside the functions listed.
        (
            "class VThermLink:\n"
            "    def zone(self, entity_id):\n"
            "        return self._hass.states.get(entity_id)\n",
            "vtherm_link.py",
            "vtherm_link.py:3 VThermLink.zone: reads a state, not listed in READS",
        ),
        # An attribute VT adds, in a function allowed to read a state.
        (
            "def relay_hvac_modes(state):\n    return state.attributes.get('specific_states')\n",
            "transport/entities.py",
            "transport/entities.py:2 relay_hvac_modes: reads the attribute 'specific_states', "
            "not Home Assistant's",
        ),
        # The same through a local name.
        (
            "def restart_reading(state):\n"
            "    attributes = state.attributes\n"
            "    return attributes['on_percent']\n",
            "transport/entities.py",
            "transport/entities.py:3 restart_reading: reads the attribute 'on_percent', "
            "not Home Assistant's",
        ),
        # Every attribute at once.
        (
            "def everything(state):\n    return dict(state.attributes)\n",
            "sensor.py",
            "sensor.py:2 everything: a state's attributes used other than by one name",
        ),
        # VT's config entries outside "VT loaded".
        (
            "def central(hass):\n    return hass.config_entries.async_entries(VT_DOMAIN)\n",
            "config_flow.py",
            "config_flow.py:2 central: VT's config entries",
        ),
        # Every config entry, VT's among them, in a function allowed to read entries.
        (
            "def mqtt_set_up(hass):\n    return hass.config_entries.async_entries()\n",
            "config_flow.py",
            "config_flow.py:2 mqtt_set_up: every config entry, VT's among them",
        ),
        # VT's own hass.data.
        (
            "def central_api(hass):\n    return hass.data[VT_DOMAIN]\n",
            "feature_manager.py",
            "feature_manager.py:2 central_api: reads VT's hass.data, not listed in READS",
        ),
        # A climate's history from the recorder.
        (
            "def past(hass, start, rooms):\n"
            "    return get_significant_states(hass, start, entity_ids=rooms)\n",
            "coordinator.py",
            "coordinator.py:2 past: reads a history or a change, not listed in READS",
        ),
        # Following a climate's changes.
        (
            "def follow(hass, rooms, changed):\n"
            "    return async_track_state_change_event(hass, rooms, changed)\n",
            "coordinator.py",
            "coordinator.py:2 follow: reads a history or a change, not listed in READS",
        ),
    ],
)
def test_the_guard_catches_a_planted_read(source: str, module: str, expected: str) -> None:
    """Negative: each kind of read the guard watches, planted where it is not allowed, is
    caught."""
    assert expected in violations(source, module, {**READS, **FOUND})
