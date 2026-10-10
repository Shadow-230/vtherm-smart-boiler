"""Config entry options parsed into core objects, with the cautious defaults."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.config import (
    ConfigError,
    EntryConfig,
    migrated_pressure_high,
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


@pytest.mark.parametrize(
    ("curve", "parameters", "expected"),
    [
        ({"design_flow": 50}, {"design_outdoor": -22}, -22.0),
        ({"design_outdoor": -20, "design_flow": 50}, {"design_outdoor": -22}, -20.0),
        ({"design_flow": 50}, {}, -15.0),
        ({"design_flow": 50}, {"design_outdoor": -42}, -42.0),
    ],
    ids=["the_buildings", "the_curves_own_first", "the_default", "below_minus_40"],
)
def test_control_reads_the_buildings_design_outdoor_temperature(
    curve: dict[str, float], parameters: dict[str, float], expected: float
) -> None:
    """I6: one design outdoor temperature, the building's, which the curve uses — within the
    building's −45 to 10 °C. A value the curve's own section still holds (a hand edit, or one the
    entry migration could not move) is read first, as before; with neither, the default."""
    options = MINIMAL | {
        "boiler": {"class": "flow_setpoint"},
        "parameters": parameters,
        "control": {
            "write_path": "opentherm_gw",
            "gateway_id": "gw",
            "confirmed_entity": "sensor.setpoint",
            "topology": "gateway_with_thermostat",
            "curve": curve,
        },
    }
    config = EntryConfig.from_options(options)
    assert config.control.loop.control.curve.design_outdoor == expected


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
        (MINIMAL | {"parameters": {"boiler_min_power": 0.0}}, "implausible_parameter"),
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


def test_unknown_keys_from_a_later_version_are_ignored_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PB-68: a signal, parameter or freshness key this version does not know (an entry saved
    by a later version, then a downgrade) is left out and logged, rather than stopping the
    entry; what is known is still read. Negative: an empty unknown key logs nothing."""
    options = MINIMAL | {
        "signals": MINIMAL["signals"] | {"bogus": "a.b", "empty": ""},
        "parameters": {"nope": 1, "boiler_max_power": 24},
        "freshness": {"flow": 600, "later": 300},
    }
    config = EntryConfig.from_options(options)
    assert config.signals == {Signal.FLAME: "binary_sensor.flame", Signal.FLOW: "sensor.flow"}
    assert config.freshness == {Signal.FLOW: 600.0}
    assert config.parameters.value(ParameterKey.BOILER_MAX_POWER) == 24.0
    logged = caplog.text
    for key in ("bogus", "nope", "later"):
        assert key in logged
    assert "empty" not in logged


def test_alarm_thresholds_default_and_options() -> None:
    from custom_components.vtherm_smart_boiler.core.alarms import (
        DEFAULT_FREQUENT_STARTS_PER_HOUR,
        add_water_band,
    )

    defaults = EntryConfig.from_options(MINIMAL).monitor.alarms
    assert defaults.pressure_low is None  # Y1: no "add water" threshold by default
    assert defaults.add_water_below is None
    assert defaults.pressure_high is None  # decision 13: no high-pressure limits by default
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


def test_the_verdict_knows_whether_control_sets_the_water() -> None:
    """S-22: low condensing is a problem 0.2.2's control changes only where it sets the water
    temperature — a flow-setpoint boiler, not switched through a relay; for the classes control
    is not offered for, and by default (read-only), nothing the verdict finds is."""

    def sets_water(options: dict) -> bool:
        return EntryConfig.from_options(options).monitor.monitor.verdict.control_sets_water

    assert sets_water(MINIMAL) is False  # read-only by default
    assert sets_water(MINIMAL | {"boiler": {"class": "flow_setpoint"}}) is True
    gateway = {"write_path": "opentherm_gw", "gateway_id": "gw"}
    flow = MINIMAL | {"boiler": {"class": "flow_setpoint"}, "control": gateway}
    assert sets_water(flow) is True
    relay = {"write_path": "relay", "relay_entity": "switch.r", "relay_is_separate_contact": True}
    assert sets_water(MINIMAL | {"boiler": {"class": "on_off"}, "control": relay}) is False
    assert sets_water(MINIMAL | {"boiler": {"class": "curve_only"}}) is False
    mixed = MINIMAL | {"boiler": {"class": "flow_setpoint"}, "control": relay}
    assert sets_water(mixed) is False  # a relay sets no water, whatever the class says


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
    condensing = features(frozenset(config.signals), False, False, shared=config.shared_signals)[
        Feature.CONDENSING
    ]
    assert condensing.status is FeatureStatus.INACTIVE
    # Y4: named as dropped, with the signal that kept the entity.
    assert condensing.missing == ("entity_for_two_signals",)
    assert condensing.shared == ((Signal.RETURN, Signal.FLOW),)
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


# PB-24 (TB-25): an underfloor circuit with its maximum, and a gateway's control section.
UNDERFLOOR = MINIMAL | {
    "boiler": {"class": "flow_setpoint"},
    "circuits": [{"id": "floor", "max_flow": 40}],
    "zones": [{"entity_id": "climate.a", "circuit": "floor", "emitter": "underfloor"}],
}
GATEWAY_CONTROL = {
    "write_path": "opentherm_gw",
    "gateway_id": "gw",
    "confirmed_entity": "sensor.setpoint",
    "topology": "gateway_standalone",
    "thermostat_kind": "none",
    "curve": {"design_outdoor": -15, "design_flow": 35},
}
NAN, INF = float("nan"), float("inf")


def _floor_circuit(**values: object) -> dict:
    return UNDERFLOOR | {"circuits": [{"id": "floor", "max_flow": 40} | values]}


def _zone(**values: object) -> dict:
    return MINIMAL | {"zones": [{"entity_id": "climate.a", "emitter": "radiator"} | values]}


@pytest.mark.parametrize(
    ("options", "code", "subject"),
    [
        *(
            (_floor_circuit(max_flow=value), "invalid_circuit", "max_flow")
            for value in ("nan", "inf", NAN, INF, -5, 500, 19.5, True)
        ),
        (_floor_circuit(max_flow_alarm="nan"), "invalid_circuit", "max_flow_alarm"),
        (_floor_circuit(max_flow_alarm=101), "invalid_circuit", "max_flow_alarm"),
        (_floor_circuit(max_flow_alarm_min=0), "invalid_circuit", "max_flow_alarm_min"),
        (_floor_circuit(fixed_temperature="-inf"), "invalid_circuit", "fixed_temperature"),
        (_zone(exponent="nan"), "invalid_zone", "exponent"),
        (_zone(reference_output_w=0), "invalid_zone", "reference_output_w"),
        (
            _zone(foreign_heat=[{"entity_id": "sensor.p", "kind": "power", "threshold": NAN}]),
            "invalid_zone",
            "foreign_heat",
        ),
        (
            _zone(foreign_heat=[{"entity_id": "sensor.t", "kind": "temperature", "threshold": 5}]),
            "invalid_zone",
            "foreign_heat",
        ),
        (
            MINIMAL | {"reference_room": {"switch_margin": "nan"}},
            "invalid_reference",
            "switch_margin",
        ),
        *(
            (MINIMAL | {"monitor": {"monitoring_days": v}}, "invalid_monitor", "monitoring_days")
            for v in ("nan", INF, 0, 6, 61, -7)
        ),
        *(
            (MINIMAL | {"monitor": {key: value}}, "invalid_monitor", key)
            for key, value in (
                ("verdict_window_days", INF),
                ("starts_per_hour_limit", INF),
                ("unstable_burns_limit", 0),
                ("pressure_high_alarm", "nan"),
                ("flue_gas_warning", 500),
                ("near_room_k", -1),
                ("condensing_return", NAN),
                ("short_burn_min", 0),
                ("foreign_heat_hold_min", -5),
            )
        ),
        (MINIMAL | {"freshness": {"flow": "nan"}}, "invalid_freshness", "flow"),
        # Below a minute and not 0 (I6: 0 switches the limit off).
        (MINIMAL | {"freshness": {"weather": 30}}, "invalid_freshness", "weather"),
        (MINIMAL | {"freshness": {"flow": -60}}, "invalid_freshness", "flow"),
        (MINIMAL | {"freshness": {"flow": False}}, "invalid_freshness", "flow"),
        (MINIMAL | {"boiler": {"condensing": "false"}}, "invalid_boiler", "condensing"),
        (MINIMAL | {"boiler": {"bypass": 1}}, "invalid_boiler", "bypass"),
    ],
)
def test_stored_numbers_outside_the_form_are_refused(
    options: dict, code: str, subject: str
) -> None:
    """PB-24 (TB-25): a number the form bounds, read back not finite or outside the form's
    bounds — a hand edit, an import — is refused naming its section, never used or widened: a
    circuit maximum of nan would drop an underfloor circuit's cap, a monitoring period of 0 days
    would let control start at once; a flag is a yes or a no, never text read as true."""
    with pytest.raises(ConfigError) as err:
        EntryConfig.from_options(options)
    assert (err.value.code, err.value.subject) == (code, subject)


def test_stored_numbers_at_the_form_bounds_are_kept() -> None:
    """The bounds themselves, and nothing stored, are read as before (the negative of PB-24)."""
    config = EntryConfig.from_options(
        _floor_circuit(max_flow=20, max_flow_alarm=100, max_flow_alarm_min=120)
        | {"monitor": {"monitoring_days": 60, "verdict_window_days": 365}}
        | {"freshness": {"flow": 60, "weather": 86400, "return": None}}
    )
    circuit = config.installation.circuits[0]
    assert (circuit.max_flow, circuit.max_flow_alarm) == (20.0, 100.0)
    assert config.monitor.monitoring_days == 60.0
    assert config.freshness[Signal.FLOW] == 60.0
    assert config.weather_max_age_s == 86400.0
    floor = EntryConfig.from_options(UNDERFLOOR | {"monitor": {"monitoring_days": None}})
    assert floor.installation.circuits[0].max_flow == 40.0
    assert floor.monitor.monitoring_days == 7.0


@pytest.mark.parametrize(
    ("changes", "key"),
    [
        ({"frost_limit": "nan"}, "frost_limit"),
        ({"frost_limit": 18, "frost_release": 20}, "frost_limit"),
        ({"curve": {"design_outdoor": -15, "design_flow": "nan"}}, "design_flow"),
        ({"fallback_setpoint": 95}, "fallback_setpoint"),
        ({"fallback_setpoint": NAN}, "fallback_setpoint"),
        ({"decision_interval_min": 0}, "decision_interval_min"),
        ({"decision_interval_min": "nan"}, "decision_interval_min"),
        ({"comfort_correction": "false"}, "comfort_correction"),
    ],
)
def test_stored_control_numbers_outside_the_form_leave_control_out(changes: dict, key: str) -> None:
    """PB-24 (TB-25): a control value the form bounds, stored not finite or outside them, is
    refused at a save (the control step shows it) and leaves control out at setup — the monitor
    runs, an owed hand-back still goes out through the options the boiler was taken with."""
    options = UNDERFLOOR | {"control": GATEWAY_CONTROL | changes}
    with pytest.raises(ConfigError) as err:
        EntryConfig.from_options(options)
    assert err.value.code == "invalid_control"
    assert key in str(err.value)
    config = EntryConfig.from_options(options, strict_control=False)
    assert not config.control.configured
    assert config.control_problem is not None
    assert key in config.control_problem
    assert EntryConfig.from_options(UNDERFLOOR | {"control": GATEWAY_CONTROL}).control.configured


SECTIONS_OF_ANOTHER_SHAPE = [
    ("signals", ["binary_sensor.flame"], "invalid_signals"),
    ("boiler", "flow_setpoint", "invalid_boiler"),
    ("circuits", {"id": "main"}, "invalid_circuit"),
    ("circuits", ["main"], "invalid_circuit"),
    ("zones", "climate.a", "invalid_zone"),
    ("zones", [["climate.a"]], "invalid_zone"),
    ("parameters", [], "invalid_parameters"),
    ("building", "big", "invalid_building"),
    ("reference_room", ["chosen_zone"], "invalid_reference"),
    ("monitor", [], "invalid_monitor"),
    ("freshness", [60], "invalid_freshness"),
    ("control", ["opentherm_gw"], "invalid_control"),
    ("control", "opentherm_gw", "invalid_control"),
]


@pytest.mark.parametrize(("section", "value", "code"), SECTIONS_OF_ANOTHER_SHAPE)
def test_a_section_of_another_shape_is_refused_naming_it(
    section: str, value: object, code: str
) -> None:
    """PB-06: a section of another shape — a list where a mapping belongs, text where a section
    belongs (a hand edit, an import) — raises a ``ConfigError`` naming it, never an
    ``AttributeError``; a control section so leaves control out at setup."""
    with pytest.raises(ConfigError) as err:
        EntryConfig.from_options(MINIMAL | {section: value})
    assert (err.value.code, err.value.subject) == (code, section)
    if section == "control":
        config = EntryConfig.from_options(MINIMAL | {section: value}, strict_control=False)
        assert not config.control.configured
        assert config.control_problem is not None


@pytest.mark.parametrize("section", sorted({s for s, _, _ in SECTIONS_OF_ANOTHER_SHAPE}))
def test_a_section_stored_as_none_reads_as_empty(section: str) -> None:
    """The negative of PB-06: a section stored as nothing (``None``) is no section."""
    config = EntryConfig.from_options(MINIMAL | {section: None})
    assert not config.control.configured


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


@pytest.mark.parametrize(
    ("monitor", "limits"),
    [
        ({}, None),
        ({"pressure_high_warning": "", "pressure_high_alarm": None}, None),
        ({"pressure_high_warning": 2.9}, (2.9, None)),
        ({"pressure_high_alarm": 1.8}, (None, 1.8)),
        ({"pressure_high_warning": 1.7, "pressure_high_alarm": 1.9}, (1.7, 1.9)),
    ],
    ids=["none", "empty", "warning_only", "alarm_only", "both"],
)
def test_the_high_pressure_limits_are_each_optional(
    monitor: dict, limits: tuple[float | None, float | None] | None
) -> None:
    """Decision 13 (SB-18): each limit optional, none by default; "alarm above the warning"
    only where both are set — one alone is never compared with a default."""
    band = EntryConfig.from_options(MINIMAL | {"monitor": monitor}).monitor.alarms.pressure_high
    assert (None if band is None else (band.warning, band.alarm)) == limits


@pytest.mark.parametrize("value", [1.4, 4.1, "high", True, float("nan")])
def test_a_high_pressure_limit_outside_the_forms_bounds_cannot_be_used(value: object) -> None:
    for key in ("pressure_high_warning", "pressure_high_alarm"):
        with pytest.raises(ConfigError) as err:
            EntryConfig.from_options(MINIMAL | {"monitor": {key: value}})
        assert (err.value.code, err.value.subject) == ("invalid_monitor", key)


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (
            {"signals": {"pressure": "sensor.p"}},
            {"pressure_high_warning": 2.5, "pressure_high_alarm": 2.8},
        ),
        (
            {"signals": {"pressure": "sensor.p"}, "monitor": {"monitoring_days": 7}},
            {"monitoring_days": 7, "pressure_high_warning": 2.5, "pressure_high_alarm": 2.8},
        ),
        (
            {"signals": {"pressure": "sensor.p"}, "monitor": {"pressure_high_alarm": 3.0}},
            {"pressure_high_warning": 2.5, "pressure_high_alarm": 3.0},
        ),
        (
            {
                "signals": {"pressure": "sensor.p"},
                "monitor": {"pressure_high_warning": 1.8, "pressure_high_alarm": 2.0},
            },
            None,
        ),
        ({"signals": {"flame": "binary_sensor.f"}}, None),
        ({"signals": {"pressure": ""}}, None),
        ({"signals": "pressure"}, None),
        ({"signals": {"pressure": "sensor.p"}, "monitor": ["pressure_high_alarm"]}, None),
    ],
    ids=[
        "no_monitor",
        "monitor_without",
        "one_stored",
        "both_stored",
        "no_pressure",
        "pressure_empty",
        "signals_of_another_shape",
        "monitor_of_another_shape",
    ],
)
def test_the_migration_keeps_the_high_pressure_limits_an_entry_ran_with(
    options: dict, expected: dict | None
) -> None:
    """Decision 13 (minor version 5): an entry from before, with the water pressure mapped,
    keeps 0.2.2's 2.5 / 2.8 bar for each limit it did not store — no alarm drops silently; a
    stored limit stays as stored. Without the pressure, or a section of another shape (refused
    by the reader with its reason), nothing is written."""
    assert migrated_pressure_high(options) == expected


# --- I6.1: the setup's first answers (decisions 1, 6, 7, 8, 12) ------------------------------

OTGW_CONTROL = {
    "write_path": "opentherm_gw",
    "gateway_id": "gw",
    "confirmed_entity": "sensor.setpoint",
    "topology": "gateway_with_thermostat",
    "thermostat_kind": "opentherm",
    "curve": {"design_outdoor": -15, "design_flow": 55},
}
ANSWERED = {
    "connection": "boiler_module",
    "control_mode": "monitor",
    "heat_source": "gas",
    "type": "combi_tank",
    "dhw_priority": False,
}


def test_an_entry_from_before_the_panel_reads_as_before() -> None:
    """Decision 12: no answer stored — nothing changes: the stored class and hot-water kind,
    the priority taken as before (hot water takes the heat), and no mode reason for control."""
    from custom_components.vtherm_smart_boiler.config import BoilerPanel

    options = MINIMAL | {"boiler": {"class": "flow_setpoint", "dhw": "combi"}}
    config = EntryConfig.from_options(options)
    assert config.panel == BoilerPanel()
    assert config.panel.dhw_priority is True
    assert config.installation.boiler.boiler_class is BoilerClass.FLOW_SETPOINT
    assert config.installation.boiler.dhw.value == "combi"
    assert config.control.connection is None
    assert config.control.control_mode is None


def test_the_panels_answers_are_read_and_decide_the_class_and_hot_water() -> None:
    """Decisions 2, 5 and 8: where the panel is answered, the class follows the connection and
    the mode, and the hot-water kind the boiler type — whatever a hand edit stored beside them."""
    from custom_components.vtherm_smart_boiler.control_config import Connection, ControlMode
    from custom_components.vtherm_smart_boiler.core.installation import BoilerType, HeatSource

    boiler = ANSWERED | {"class": "flow_setpoint", "dhw": "none"}
    config = EntryConfig.from_options(MINIMAL | {"boiler": boiler})
    panel = config.panel
    assert panel.connection is Connection.BOILER_MODULE
    assert panel.control_mode is ControlMode.MONITOR
    assert panel.heat_source is HeatSource.GAS
    assert panel.boiler_type is BoilerType.COMBI_TANK
    assert panel.dhw_priority is False
    assert config.installation.boiler.boiler_class is BoilerClass.READ_ONLY
    assert config.installation.boiler.dhw.value == "storage"
    assert config.monitor.monitor.has_dhw
    assert config.control.connection is Connection.BOILER_MODULE
    assert config.control.control_mode is ControlMode.MONITOR


@pytest.mark.parametrize(
    ("changes", "subject"),
    [
        ({"connection": "carrier_pigeon"}, "connection"),
        ({"control_mode": "telepathy"}, "control_mode"),
        ({"heat_source": "peat"}, "heat_source"),
        ({"type": "triple"}, "type"),
        ({"dhw_priority": "yes"}, "dhw_priority"),
        # A mode the connection cannot do (a hand edit): a relay cannot set the water.
        ({"connection": "relay", "control_mode": "full"}, "control_mode"),
    ],
)
def test_an_answer_this_version_cannot_read(changes: dict, subject: str) -> None:
    """Decision 12 (P-70): an answer this version does not know is refused naming the panel;
    at setup it leaves control out, the monitor running — and with no control section there is
    nothing to leave out."""
    boiler = {"boiler": ANSWERED | changes}
    with pytest.raises(ConfigError) as err:
        EntryConfig.from_options(MINIMAL | boiler)
    assert (err.value.code, err.value.subject) == ("invalid_connection", subject)
    config = EntryConfig.from_options(
        MINIMAL | boiler | {"control": OTGW_CONTROL}, strict_control=False
    )
    assert not config.control.configured
    assert config.control_problem == f"invalid_connection: {subject}"
    config = EntryConfig.from_options(MINIMAL | boiler, strict_control=False)
    assert config.control_problem is None
    assert config.signals  # the monitor runs


def test_monitoring_only_keeps_a_stored_control_section_from_running() -> None:
    """Decision 6: with monitoring only chosen, a control section left from before is parsed,
    and its one blocker is the mode."""
    from custom_components.vtherm_smart_boiler.control_config import config_blockers

    boiler = {"connection": "opentherm_gw", "control_mode": "monitor"}
    config = EntryConfig.from_options(MINIMAL | {"boiler": boiler, "control": OTGW_CONTROL})
    assert config.control.configured
    blockers = config_blockers(config.control, config.installation)
    assert blockers == ["control_mode_monitor"]


def test_a_stored_zero_switches_a_freshness_limit_off() -> None:
    """I6.5 (decision 9): nothing stored is the automatic limit; a stored 0 is the user's "no
    limit" — availability only — for a signal and for the weather alike."""
    from custom_components.vtherm_smart_boiler.config import FRESHNESS_OFF

    config = EntryConfig.from_options(
        MINIMAL | {"weather": "weather.home", "freshness": {"flow": 0, "weather": 0}}
    )
    assert config.freshness == {Signal.FLOW: FRESHNESS_OFF}
    assert config.weather_max_age_s == FRESHNESS_OFF
    assert EntryConfig.from_options(MINIMAL).weather_max_age_s is None
