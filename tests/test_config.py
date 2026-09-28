"""Config entry options parsed into core objects, with the cautious defaults."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.config import (
    ConfigError,
    EntryConfig,
    named_entities,
    rename_entity,
)
from custom_components.vtherm_smart_boiler.core.foreign_heat import SourceKind
from custom_components.vtherm_smart_boiler.core.installation import (
    BoilerClass,
    CircuitControl,
    EmitterType,
)
from custom_components.vtherm_smart_boiler.core.metrics import ModulationScale
from custom_components.vtherm_smart_boiler.core.parameters import ParameterKey, Source
from custom_components.vtherm_smart_boiler.core.reference_room import Strategy
from custom_components.vtherm_smart_boiler.core.signals import Signal

MINIMAL = {"signals": {"flame": "binary_sensor.flame", "flow": "sensor.flow"}}


def test_minimal_options_get_cautious_defaults() -> None:
    config = EntryConfig.from_options(MINIMAL)
    assert config.level == "simple"
    assert config.signals == {Signal.FLAME: "binary_sensor.flame", Signal.FLOW: "sensor.flow"}
    assert config.installation.boiler.boiler_class is BoilerClass.READ_ONLY
    assert [c.circuit_id for c in config.installation.circuits] == ["main"]
    assert config.zones == ()
    assert config.weather is None
    assert config.weather_max_age_s is None  # no age limit: availability only
    assert config.reference_room.strategy is Strategy.LARGEST_DEFICIT
    assert config.monitor.monitoring_days == 7.0
    assert config.monitor.monitor.modulation_scale is ModulationScale.RANGE
    assert config.parameters.value(ParameterKey.HEATING_THRESHOLD) == 15.0  # class default
    assert config.watched_entities == ("binary_sensor.flame", "sensor.flow")
    assert not config.control.configured


def test_control_section_uses_the_boilers_maximum() -> None:
    options = MINIMAL | {
        "boiler": {"class": "flow_setpoint"},
        "parameters": {"max_ch_setpoint": 60},
        "control": {
            "write_path": "opentherm_gw",
            "gateway_id": "gw",
            "confirmed_entity": "sensor.setpoint",
            "topology": "gateway_with_thermostat",
            "curve": {"design_outdoor": -20, "design_flow": 50},
        },
    }
    control = EntryConfig.from_options(options).control
    assert control.configured
    assert control.loop.control.boiler_max == 60.0
    assert control.loop.control.curve.design_flow == 50.0


def test_full_options() -> None:
    options = {
        "level": "advanced",
        "signals": {
            "flame": "binary_sensor.flame",
            "flow": "sensor.flow",
            "return": "sensor.ret",
            "gas_meter": "",
        },
        "weather": "weather.home",
        "boiler": {"class": "flow_setpoint", "dhw": "storage", "modulation_scale": "capacity"},
        "parameters": {"boiler_min_power": 4, "boiler_max_power": 24, "design_outdoor": 0.0},
        "circuits": [
            {"id": "c1", "control": "unmixed_shared", "max_flow": 45},
            {"id": "c2", "control": "separate", "flow_entity": "sensor.mixed_flow"},
        ],
        "zones": [
            {
                "entity_id": "climate.a",
                "circuit": "c1",
                "emitter": "underfloor",
                "foreign_heat": [
                    {"entity_id": "switch.fire", "kind": "switch"},
                    {"entity_id": "sensor.stove", "kind": "temperature", "threshold": 60},
                ],
            },
            {"entity_id": "climate.b", "circuit": "c2", "reference_output_w": 1500},
        ],
        "building": {"design_load_kw": 8.0, "thermal_mass": "heavy"},
        "reference_room": {"strategy": "chosen_zone", "zone": "climate.b"},
        "monitor": {"condensing_return": 52, "short_burn_min": 8, "monitoring_days": 10},
        "freshness": {"flow": 600, "pressure": None},
    }
    config = EntryConfig.from_options(options)
    assert Signal.GAS_METER not in config.signals  # an empty field is not mapped
    assert config.installation.boiler.boiler_class is BoilerClass.FLOW_SETPOINT
    assert config.installation.circuit("c2").control is CircuitControl.SEPARATE
    assert config.circuit_flow_entities == {"c2": "sensor.mixed_flow"}
    assert config.installation.zone("climate.a").emitter is EmitterType.UNDERFLOOR
    assert config.zones[0].foreign_heat[1].kind is SourceKind.TEMPERATURE
    assert config.zones[0].foreign_heat[1].threshold == 60.0
    # design load 8 kW between 20 °C indoor and a 0 °C design outdoor temperature
    loss = config.parameters.get(ParameterKey.LOSS_COEFFICIENT).effective()
    assert loss is not None
    assert loss.value == pytest.approx(0.4)
    assert loss.source is Source.ENTERED
    mass = config.parameters.get(ParameterKey.THERMAL_TIME_CONSTANT).effective()
    assert mass is not None
    assert mass.value == 120.0
    assert mass.source is Source.DEFAULT  # a coarse answer, until measured
    assert config.reference_room.zone == "climate.b"
    assert config.monitor.monitor.condensing_return == 52.0
    assert config.monitor.monitor.short_burn_s == 480.0
    assert config.monitor.monitor.verdict.min_days == 10.0
    assert config.freshness == {Signal.FLOW: 600.0, Signal.PRESSURE: None}
    assert "switch.fire" in config.watched_entities
    assert "sensor.mixed_flow" in config.watched_entities
    assert "weather.home" in config.watched_entities


@pytest.mark.parametrize(
    ("freshness", "signals", "weather"),
    [
        ({"outdoor": 600, "weather": 1800}, {Signal.OUTDOOR: 600.0}, 1800.0),
        ({"outdoor": 600}, {Signal.OUTDOOR: 600.0}, None),
        ({"weather": None}, {}, None),
        ({}, {}, None),
    ],
    ids=["both", "sensor_only", "weather_none", "none"],
)
def test_the_weather_entity_has_an_age_limit_of_its_own(
    freshness: dict, signals: dict, weather: float | None
) -> None:
    """P-41 (X2): ``freshness["weather"]`` is the weather entity's own limit, taken out before
    the signals are read — never the outdoor sensor's, never a signal; none by default."""
    config = EntryConfig.from_options(MINIMAL | {"weather": "weather.home", "freshness": freshness})
    assert config.freshness == signals
    assert config.weather_max_age_s == weather


def test_coarse_building_answers_give_a_default_loss() -> None:
    options = MINIMAL | {"building": {"floor_area": 140, "insulation": "good"}}
    loss = EntryConfig.from_options(options).parameters.get(ParameterKey.LOSS_COEFFICIENT)
    effective = loss.effective()
    assert effective is not None
    assert effective.source is Source.DEFAULT
    assert effective.value == pytest.approx(140 * 50 / 1000 / 35)


@pytest.mark.parametrize(
    ("options", "code"),
    [
        (MINIMAL | {"signals": MINIMAL["signals"] | {"bogus": "a.b"}}, "unknown_signal"),
        (MINIMAL | {"parameters": {"boiler_min_power": 0.0}}, "implausible_parameter"),
        (MINIMAL | {"parameters": {"nope": 1}}, "unknown_parameter"),
        (MINIMAL | {"zones": [{"entity_id": "climate.a", "circuit": "ghost"}]}, "unknown_circuit"),
        (
            MINIMAL
            | {"circuits": [{"id": "a"}, {"id": "b"}], "zones": [{"entity_id": "climate.x"}]},
            "zone_without_circuit",
        ),
        (
            MINIMAL | {"circuits": [{"id": "t", "control": "passive_fixed"}]},
            "fixed_temperature_missing",
        ),
        (
            MINIMAL | {"reference_room": {"strategy": "chosen_zone", "zone": "climate.x"}},
            "reference_zone_unknown",
        ),
        (MINIMAL | {"control": {"write_path": "carrier_pigeon"}}, "invalid_control"),
        (
            MINIMAL | {"control": {"write_path": "entity", "ch_write_type": "sometimes"}},
            "invalid_control",
        ),
    ],
)
def test_unusable_options(options: dict, code: str) -> None:
    with pytest.raises(ConfigError) as err:
        EntryConfig.from_options(options)
    assert err.value.code == code


def test_alarm_thresholds_default_and_options() -> None:
    from custom_components.vtherm_smart_boiler.core.alarms import (
        DEFAULT_FREQUENT_STARTS_PER_HOUR,
        add_water_band,
    )

    defaults = EntryConfig.from_options(MINIMAL).monitor.alarms
    assert defaults.pressure_low is None  # Y1: no "add water" threshold by default
    assert defaults.add_water_below is None
    assert defaults.starts_per_hour == DEFAULT_FREQUENT_STARTS_PER_HOUR
    options = MINIMAL | {
        "monitor": {
            "add_water_below": 0.8,
            "pressure_high_warning": 2.2,
            "pressure_high_alarm": 2.6,
            "flue_gas_warning": 70,
            "flue_gas_alarm": 90,
            "starts_per_hour_limit": 8,
            "unstable_burns_limit": 5,
        }
    }
    alarms = EntryConfig.from_options(options).monitor.alarms
    assert alarms.pressure_low == add_water_band(0.8)
    assert alarms.add_water_below == 0.8
    assert (alarms.pressure_high.warning, alarms.pressure_high.alarm) == (2.2, 2.6)
    assert (alarms.flue_gas.warning, alarms.flue_gas.alarm) == (70.0, 90.0)
    assert (alarms.starts_per_hour, alarms.unstable_burns_per_day) == (8, 5)


def test_the_old_low_pressure_limits_are_no_longer_read() -> None:
    """Y1: 0.2.1's warning and alarm below 1.0 / 0.7 bar are gone — stored ones (the entry
    migration drops them) give no low-pressure alarm."""
    options = MINIMAL | {"monitor": {"pressure_low_warning": 1.0, "pressure_low_alarm": 0.7}}
    assert EntryConfig.from_options(options).monitor.alarms.pressure_low is None


@pytest.mark.parametrize("value", [0.05, 2.5, "a lot", -1])
def test_an_add_water_threshold_outside_its_range_cannot_be_used(value: object) -> None:
    """A hand edit outside 0.1–2.0 bar is shown on the monitor step (P-70)."""
    with pytest.raises(ConfigError) as err:
        EntryConfig.from_options(MINIMAL | {"monitor": {"add_water_below": value}})
    assert (err.value.code, err.value.subject) == ("invalid_monitor", "add_water_below")


@pytest.mark.parametrize(
    "monitor",
    [
        {"pressure_high_warning": 2.9, "pressure_high_alarm": 2.8},
        {"flue_gas_warning": 100, "flue_gas_alarm": 90},
    ],
)
def test_alarm_limits_must_be_in_order(monitor: dict) -> None:
    with pytest.raises(ConfigError) as err:
        EntryConfig.from_options(MINIMAL | {"monitor": monitor})
    assert err.value.code == "alarm_limits_out_of_order"


def test_a_broken_control_section_keeps_the_monitor_at_setup() -> None:
    """The flow refuses such options; at setup — options saved by an older version that a newer
    check refuses — control is left out with its problem named, and the monitor keeps running."""
    options = MINIMAL | {"control": {"write_path": "entity", "ch_write_type": "sometimes"}}
    with pytest.raises(ConfigError):
        EntryConfig.from_options(options)
    config = EntryConfig.from_options(options, strict_control=False)
    assert not config.control.configured
    assert config.control_problem is not None
    assert EntryConfig.from_options(MINIMAL, strict_control=False).control_problem is None


def test_the_verdict_window_is_never_shorter_than_the_monitoring_period() -> None:
    options = {
        "signals": {"flame": "binary_sensor.flame", "flow": "sensor.flow"},
        "monitor": {"monitoring_days": 14, "verdict_window_days": 7},
    }
    assert EntryConfig.from_options(options).monitor.monitor.verdict_window_days == 14
    options["monitor"] = {"monitoring_days": 7}
    assert EntryConfig.from_options(options).monitor.monitor.verdict_window_days is None


def test_the_verdict_knows_whether_the_boiler_condenses() -> None:
    assert EntryConfig.from_options(MINIMAL).monitor.monitor.verdict.condensing_boiler is True
    options = MINIMAL | {"boiler": {"condensing": False}}
    verdict = EntryConfig.from_options(options).monitor.monitor.verdict
    assert verdict.condensing_boiler is False


# --- X4: the circuit maximum's alarm (decision 10), the zone's "closes when off" (decision 4) ---


def test_a_circuit_with_a_maximum_gets_its_alarm_temperature_and_time() -> None:
    """Pre-filled when absent — the maximum + 5 K and 10 minutes — so never empty; a stored
    value wins; a circuit without a maximum has no alarm."""
    options = MINIMAL | {"circuits": [{"id": "main", "max_flow": 40}]}
    circuit = EntryConfig.from_options(options).installation.circuits[0]
    assert (circuit.max_flow_alarm, circuit.max_flow_alarm_s) == (45.0, 600.0)
    stored = {"id": "main", "max_flow": 40, "max_flow_alarm": 48, "max_flow_alarm_min": 20}
    circuit = EntryConfig.from_options(MINIMAL | {"circuits": [stored]}).installation.circuits[0]
    assert (circuit.max_flow_alarm, circuit.max_flow_alarm_s) == (48.0, 1200.0)
    plain = EntryConfig.from_options(MINIMAL | {"circuits": [{"id": "main"}]})
    assert plain.installation.circuits[0].max_flow_alarm is None
    assert plain.installation.circuits[0].max_flow_alarm_s is None
    # Negative: a stored alarm left behind without its maximum raises nothing.
    orphan = {"id": "main", "max_flow_alarm": 48, "max_flow_alarm_min": 20}
    circuit = EntryConfig.from_options(MINIMAL | {"circuits": [orphan]}).installation.circuits[0]
    assert circuit.max_flow_alarm is None


def test_the_zone_option_closes_when_off_is_read_from_the_zone_item() -> None:
    """Decision 4: off unless stored as a clear true (the form shows it from X5)."""
    zones = [
        {"entity_id": "climate.a", "closes_when_off": True},
        {"entity_id": "climate.b", "closes_when_off": "yes"},
        {"entity_id": "climate.c"},
    ]
    installation = EntryConfig.from_options(MINIMAL | {"zones": zones}).installation
    assert [z.closes_when_off for z in installation.zones] == [True, False, False]


# --- X5: one entity, one signal (P-16, T-32); unknown stored values (P-70) -----------------------


@pytest.mark.parametrize(
    "stored",
    [
        {"flame": "binary_sensor.flame", "flow": "sensor.flow", "return": "sensor.flow"},
        # Stored in another order: the form's order still decides which signal keeps it.
        {"return": "sensor.flow", "flame": "binary_sensor.flame", "flow": "sensor.flow"},
    ],
    ids=["form_order", "stored_reversed"],
)
def test_one_entity_for_two_signals_drops_the_later_one(stored: dict) -> None:
    """X5.2: the first signal in the form's order keeps a shared entity and the later one is
    dropped — absent from the signals, so the feature that needs it is inactive and names it —
    and control gets the blocker ``entity_for_two_signals``. No ``ConfigError``: the monitor
    runs."""
    from custom_components.vtherm_smart_boiler.control_config import config_blockers
    from custom_components.vtherm_smart_boiler.core.signal_check import (
        Feature,
        FeatureStatus,
        features,
    )

    options = {
        "signals": stored,
        "boiler": {"class": "flow_setpoint"},
        "zones": [{"entity_id": "climate.a"}],
        "control": {
            "write_path": "opentherm_gw",
            "gateway_id": "gw",
            "confirmed_entity": "sensor.setpoint",
            "topology": "gateway_with_thermostat",
            "thermostat_kind": "opentherm",
            "curve": {"design_outdoor": -15, "design_flow": 55},
        },
    }
    config = EntryConfig.from_options(options)
    assert config.signals == {Signal.FLAME: "binary_sensor.flame", Signal.FLOW: "sensor.flow"}
    assert config.shared_signals == {Signal.RETURN: Signal.FLOW}
    condensing = features(frozenset(config.signals), False, False)[Feature.CONDENSING]
    assert condensing.status is FeatureStatus.UNAVAILABLE
    assert condensing.missing == (Signal.RETURN,)
    blockers = config_blockers(config.control, config.installation, config.shared_signals)
    assert blockers == ["entity_for_two_signals"]
    # The control's setpoint read-back is watched too, without a CH setpoint signal (X6).
    assert config.watched_entities == (
        "binary_sensor.flame",
        "sensor.flow",
        "climate.a",
        "sensor.setpoint",
    )


@pytest.mark.parametrize(
    "extra",
    [{"return": "sensor.return"}, {"return": ""}, {"return": None}, {}],
    ids=["different", "empty", "none", "absent"],
)
def test_different_or_empty_signal_entities_are_kept(extra: dict) -> None:
    """Negative: two different entities are both kept; a field left empty is never a
    duplicate."""
    config = EntryConfig.from_options({"signals": MINIMAL["signals"] | extra})
    assert config.shared_signals == {}
    assert (Signal.RETURN in config.signals) is bool(extra.get("return"))


def test_the_form_lists_the_signals_in_their_precedence() -> None:
    """The form's order and the parser's precedence are one list."""
    from custom_components.vtherm_smart_boiler.config_flow import SIGNAL_FIELDS
    from custom_components.vtherm_smart_boiler.core.signals import SIGNAL_PRECEDENCE

    assert tuple(SIGNAL_FIELDS) == tuple(signal.value for signal in SIGNAL_PRECEDENCE)
    assert set(SIGNAL_PRECEDENCE) == set(Signal)


@pytest.mark.parametrize(
    ("options", "code", "subject"),
    [
        (MINIMAL | {"boiler": {"class": "steam"}}, "invalid_boiler", "class"),
        (MINIMAL | {"boiler": {"dhw": "tea"}}, "invalid_boiler", "dhw"),
        (MINIMAL | {"boiler": {"modulation_scale": "loud"}}, "invalid_boiler", "modulation_scale"),
        (
            MINIMAL | {"circuits": [{"id": "main", "control": "magic"}]},
            "invalid_circuit",
            "control",
        ),
        (
            MINIMAL | {"circuits": [{"id": "main", "max_flow": "hot"}]},
            "invalid_circuit",
            "max_flow",
        ),
        (MINIMAL | {"circuits": [{"control": "unmixed_shared"}]}, "invalid_circuit", "id"),
        (
            MINIMAL | {"zones": [{"entity_id": "climate.a", "emitter": "fireplace"}]},
            "invalid_zone",
            "emitter",
        ),
        (
            MINIMAL
            | {
                "zones": [
                    {
                        "entity_id": "climate.a",
                        "foreign_heat": [{"entity_id": "x.y", "kind": "dragon"}],
                    }
                ]
            },
            "invalid_zone",
            "foreign_heat",
        ),
        (MINIMAL | {"zones": [{"emitter": "radiator"}]}, "invalid_zone", "entity_id"),
        (MINIMAL | {"reference_room": {"strategy": "loudest"}}, "invalid_reference", "strategy"),
        (
            MINIMAL | {"reference_room": {"switch_margin": "wide"}},
            "invalid_reference",
            "switch_margin",
        ),
        (
            MINIMAL | {"monitor": {"monitoring_days": "a week"}},
            "invalid_monitor",
            "monitoring_days",
        ),
        (MINIMAL | {"building": {"thermal_mass": "granite"}}, "invalid_building", "thermal_mass"),
        (
            MINIMAL | {"building": {"floor_area": 120, "insulation": "straw"}},
            "invalid_building",
            "insulation",
        ),
        (MINIMAL | {"freshness": {"flow": "soon"}}, "invalid_freshness", "flow"),
    ],
)
def test_unknown_stored_values_name_their_section(options: dict, code: str, subject: str) -> None:
    """P-70: a value this version does not know — a hand edit, an option of another version —
    raises a ``ConfigError`` naming its section (the form shows it on that section's step),
    never a bare ``ValueError``."""
    with pytest.raises(ConfigError) as err:
        EntryConfig.from_options(options)
    assert (err.value.code, err.value.subject) == (code, subject)


@pytest.mark.parametrize(
    ("signals", "control", "recorded"),
    [
        ({}, {"write_path": "opentherm_gw", "confirmed_entity": "sensor.setpoint"}, True),
        (
            {"ch_setpoint": "sensor.ch"},
            {"write_path": "opentherm_gw", "confirmed_entity": "s"},
            False,
        ),
        ({}, {}, False),  # no control: no read-back
        ({}, {"write_path": "opentherm_gw"}, False),  # control without a read-back
    ],
)
def test_the_setpoint_read_back_is_recorded_without_a_setpoint_signal(
    signals: dict, control: dict, recorded: bool
) -> None:
    """X6: the lowest water temperature's evidence needs the setpoint in force; without the
    boiler's CH setpoint signal, the control's read-back is recorded into the history (and
    watched); with the signal, or without control, nothing more is watched."""
    options = MINIMAL | {"signals": MINIMAL["signals"] | signals, "control": control}
    config = EntryConfig.from_options(options, strict_control=False)
    read_back = control.get("confirmed_entity") if recorded else None
    assert config.setpoint_read_back == read_back
    assert (read_back in config.watched_entities) is recorded


# P-19 (X7): every entity the options name, so a rename can be followed and a removal told.
NAMING = {
    "signals": {"flame": "binary_sensor.flame", "flow": "sensor.flow", "outdoor": "sensor.out"},
    "weather": "weather.home",
    "boiler": {"class": "flow_setpoint"},
    "circuits": [{"id": "main", "flow_entity": "sensor.circuit_flow"}],
    "zones": [
        {
            "entity_id": "climate.living",
            "circuit": "main",
            "foreign_heat": [{"entity_id": "switch.stove", "kind": "switch"}],
        },
        {"entity_id": "climate.bedroom", "circuit": "main"},
    ],
    "reference_room": {"strategy": "chosen_zone", "zone": "climate.living"},
    "freshness": {"flow": 600},
    "control": {
        "write_path": "entity",
        "topology": "virtual",
        "setpoint_entity": "number.setpoint",
        "ch_entity": "switch.heating",
        "hand_back_entity": "switch.external",
        "confirmed_entity": "sensor.confirmed",
        "ch_confirmed_entity": "binary_sensor.heating_echo",
        "thermostat_setpoint_entity": "sensor.thermostat_setpoint",
        "restart_entity": "sensor.uptime",
        "frost_zone": "climate.bedroom",
        "curve": {"design_outdoor": -20, "design_flow": 50},
    },
}


def test_every_entity_the_options_name_is_found_with_its_fields() -> None:
    assert named_entities(NAMING) == {
        "binary_sensor.flame": ("signals.flame",),
        "sensor.flow": ("signals.flow",),
        "sensor.out": ("signals.outdoor",),
        "weather.home": ("weather",),
        "sensor.circuit_flow": ("circuits.main.flow_entity",),
        "climate.living": ("zones", "reference_room.zone"),
        "switch.stove": ("zones.foreign_heat (climate.living)",),
        "climate.bedroom": ("zones", "control.frost_zone"),
        "number.setpoint": ("control.setpoint_entity",),
        "switch.heating": ("control.ch_entity",),
        "switch.external": ("control.hand_back_entity",),
        "sensor.confirmed": ("control.confirmed_entity",),
        "binary_sensor.heating_echo": ("control.ch_confirmed_entity",),
        "sensor.thermostat_setpoint": ("control.thermostat_setpoint_entity",),
        "sensor.uptime": ("control.restart_entity",),
    }
    # Every entity the entry follows is among them.
    assert set(EntryConfig.from_options(NAMING).watched_entities) <= set(named_entities(NAMING))


@pytest.mark.parametrize(
    ("old", "new", "changed"),
    [
        ("climate.living", "climate.lounge", ("zones", "reference_room")),
        ("climate.bedroom", "climate.guest_room", ("zones", "control")),
        ("sensor.flow", "sensor.boiler_flow", ("signals",)),
        ("switch.stove", "switch.fireplace", ("zones",)),
        ("sensor.circuit_flow", "sensor.radiator_flow", ("circuits",)),
        ("weather.home", "weather.house", ("weather",)),
        ("number.setpoint", "number.boiler_setpoint", ("control",)),
    ],
)
def test_a_renamed_entity_is_replaced_wherever_the_options_name_it(
    old: str, new: str, changed: tuple[str, ...]
) -> None:
    import copy

    before = copy.deepcopy(NAMING)
    renamed = rename_entity(NAMING, old, new)
    assert NAMING == before  # the stored options are not touched
    assert old not in named_entities(renamed)
    assert named_entities(renamed)[new] == named_entities(NAMING)[old]
    assert {key for key in NAMING if renamed[key] != NAMING[key]} == set(changed)
    EntryConfig.from_options(renamed)  # still options this version reads


@pytest.mark.parametrize(
    "old",
    [
        "climate.elsewhere",  # an entity the options do not name
        "main",  # a circuit's ID is no entity
        "flow",  # nor is a signal's key
        "chosen_zone",  # nor an option's value
    ],
)
def test_renaming_what_the_options_do_not_name_as_an_entity_changes_nothing(old: str) -> None:
    assert rename_entity(NAMING, old, "sensor.new") == NAMING


@pytest.mark.parametrize(
    "broken",
    [
        {"signals": None, "zones": "climate.a", "circuits": {"id": "main"}},
        {"zones": [None, {"entity_id": None}, {"entity_id": "climate.a", "foreign_heat": None}]},
        {"reference_room": "climate.a", "control": ["setpoint_entity"], "weather": 5},
        {},
    ],
)
def test_options_of_another_shape_name_what_they_can_and_never_raise(broken: dict) -> None:
    """Missing data: a hand edit of another shape is read as far as it goes; nothing raises."""
    found = named_entities(broken)
    assert set(found) <= {"climate.a"}
    assert rename_entity(broken, "climate.a", "climate.b") is not None


def test_an_entry_without_boiler_signals_parses() -> None:
    """X8 (R4): flame and flow are optional for the whole entry — a home with only a relay is
    monitored too; no signal at all, or flame without flow, parses."""
    for signals in ({}, {"flame": "binary_sensor.flame"}, {"flow": "sensor.flow"}):
        config = EntryConfig.from_options({"signals": signals})
        assert set(config.signals) == {Signal(key) for key in signals}
        assert config.shared_signals == {}
    config = EntryConfig.from_options({})
    assert config.signals == {}


def test_flame_and_flow_sharing_one_entity_drop_the_flow() -> None:
    """X5's carry-over: one entity for flame and flow (a hand edit) — the flow is dropped as a
    shared signal, never a ``missing_signal`` for the whole entry."""
    config = EntryConfig.from_options({"signals": {"flame": "sensor.x", "flow": "sensor.x"}})
    assert config.signals == {Signal.FLAME: "sensor.x"}
    assert config.shared_signals == {Signal.FLOW: Signal.FLAME}


def test_the_boiler_power_signal_parses() -> None:
    """R4: the boiler's electric power, a power sensor in W (kW converted), plausible to
    100 kW; used only as a relay's proof that the boiler heats."""
    from custom_components.vtherm_smart_boiler.core.signals import (
        SIGNAL_PRECEDENCE,
        SIGNAL_SPECS,
        SignalKind,
    )
    from custom_components.vtherm_smart_boiler.units import signal_value

    config = EntryConfig.from_options({"signals": {"boiler_power": "sensor.plug_power"}})
    assert config.signals == {Signal.BOILER_POWER: "sensor.plug_power"}
    assert SIGNAL_SPECS[Signal.BOILER_POWER].kind is SignalKind.POWER
    assert Signal.BOILER_POWER in SIGNAL_PRECEDENCE
    assert signal_value(Signal.BOILER_POWER, "120", "W") == 120.0
    assert signal_value(Signal.BOILER_POWER, "0.12", "kW") == pytest.approx(120.0)
    assert signal_value(Signal.BOILER_POWER, "120", None) == 120.0  # no unit: W
    assert signal_value(Signal.BOILER_POWER, "200", "kW") is None  # beyond 100 kW
    assert signal_value(Signal.BOILER_POWER, "-5", "W") is None
    assert signal_value(Signal.BOILER_POWER, "120", "V") is None  # not a power unit
    assert signal_value(Signal.BOILER_POWER, "unavailable", "W") is None


def test_a_relay_control_section_parses() -> None:
    options = {
        "boiler": {"class": "on_off"},
        "zones": [{"entity_id": "climate.a"}],
        "control": {
            "write_path": "relay",
            "relay_entity": "switch.boiler_relay",
            "relay_is_separate_contact": True,
            "relay_reports_state": "yes",
        },
    }
    config = EntryConfig.from_options(options)
    assert config.control.configured
    assert config.control.relay.entity == "switch.boiler_relay"
    assert "switch.boiler_relay" in named_entities(options)
    assert named_entities(options)["switch.boiler_relay"] == ("control.relay_entity",)
