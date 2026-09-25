"""Config entry options parsed into core objects, with the cautious defaults."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.config import ConfigError, EntryConfig
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
        ({"signals": {"flame": "binary_sensor.flame"}}, "missing_signal"),
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
        PRESSURE_LOW_BAND,
    )

    defaults = EntryConfig.from_options(MINIMAL).monitor.alarms
    assert defaults.pressure_low == PRESSURE_LOW_BAND
    assert defaults.starts_per_hour == DEFAULT_FREQUENT_STARTS_PER_HOUR
    options = MINIMAL | {
        "monitor": {
            "pressure_low_warning": 1.2,
            "pressure_low_alarm": 0.9,
            "pressure_high_warning": 2.2,
            "pressure_high_alarm": 2.6,
            "flue_gas_warning": 70,
            "flue_gas_alarm": 90,
            "starts_per_hour_limit": 8,
            "unstable_burns_limit": 5,
        }
    }
    alarms = EntryConfig.from_options(options).monitor.alarms
    assert (alarms.pressure_low.warning, alarms.pressure_low.alarm) == (1.2, 0.9)
    assert (alarms.pressure_high.warning, alarms.pressure_high.alarm) == (2.2, 2.6)
    assert (alarms.flue_gas.warning, alarms.flue_gas.alarm) == (70.0, 90.0)
    assert (alarms.starts_per_hour, alarms.unstable_burns_per_day) == (8, 5)


@pytest.mark.parametrize(
    "monitor",
    [
        {"pressure_low_warning": 0.8, "pressure_low_alarm": 0.9},
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
