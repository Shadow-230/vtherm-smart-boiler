"""History importer: mapping, reading a recorder copy into History, the report and the CLI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom_components.vtherm_smart_boiler.core.parameters import ParameterKey
from custom_components.vtherm_smart_boiler.core.signals import Signal
from tools.import_history import (
    MappingError,
    local_days,
    main,
    parse_mapping,
    read_history,
    report,
)
from tools.recorder_db import RecorderDatabase

from .recorder_fixture import RecorderWriter

MIN = 60.0
HOUR = 3600.0
DAY = 86400.0
T0 = 1_780_000_000.0  # a fixed instant

MAPPING = {
    "boiler": {
        "flame": "binary_sensor.test_flame",
        "flow": "sensor.test_flow",
        "return": "sensor.test_return",
        "modulation": "sensor.test_modulation",
    },
    "weather": {"entity": "weather.test"},
    "zones": {"living": "climate.test_living"},
    "parameters": {"boiler_min_power": 4.0, "boiler_max_power": 20.0},
    "options": {"temperature_unit": "°F"},
}


@pytest.fixture
def recorder(tmp_path: Path) -> Path:
    writer = RecorderWriter(tmp_path / "home-assistant_v2.db")
    celsius = {"unit_of_measurement": "°C"}
    writer.add("sensor.test_modulation", T0, "25", {"unit_of_measurement": "%"})
    writer.add("sensor.test_return", T0, "38.0", celsius)
    writer.add("weather.test", T0, "cloudy", {"temperature": 41.0, "temperature_unit": "°F"})
    writer.add(
        "climate.test_living",
        T0,
        "heat",
        {
            "current_temperature": 68.0,
            "temperature": 69.8,
            "hvac_action": "heating",
            "valve_open_percent": 60,
        },
    )
    for k in range(int(2 * DAY // (30 * MIN))):
        t = T0 + k * 30 * MIN
        writer.add("binary_sensor.test_flame", t, "off")
        writer.add("sensor.test_flow", t, "35.0", celsius)
        writer.add("binary_sensor.test_flame", t + 10 * MIN, "on")
        writer.add("sensor.test_flow", t + 10 * MIN, "45.0", celsius)
    writer.add("sensor.test_flow", T0 + HOUR, "unavailable", {})
    writer.add("sensor.test_flow", T0 + HOUR + 60, "35.0", celsius)
    return writer.close()


def test_mapping_requires_flame_and_flow_and_known_names() -> None:
    with pytest.raises(MappingError, match="flow"):
        parse_mapping({"boiler": {"flame": "binary_sensor.x"}})
    with pytest.raises(MappingError, match="not a known signal"):
        parse_mapping({"boiler": {"flame": "binary_sensor.x", "flow": "sensor.y", "bogus": "a.b"}})
    with pytest.raises(MappingError, match="entity ID"):
        parse_mapping({"boiler": {"flame": "binary_sensor.x", "flow": "nodot"}})
    with pytest.raises(MappingError, match="not a known parameter"):
        parse_mapping({"boiler": {"flame": "a.b", "flow": "c.d"}, "parameters": {"x": 1}})
    mapping = parse_mapping(MAPPING)
    assert mapping.parameters.value(ParameterKey.BOILER_MIN_POWER) == 4.0
    assert mapping.temperature_unit == "°F"


def test_read_history_converts_and_keeps_unknowns(recorder: Path) -> None:
    mapping = parse_mapping(MAPPING)
    with RecorderDatabase(recorder) as db:
        history = read_history(db, mapping, T0, T0 + 2 * DAY)
    assert set(history.signals) == {Signal.FLAME, Signal.FLOW, Signal.RETURN, Signal.MODULATION}
    flow = history.signal(Signal.FLOW)
    assert flow.value_at(T0 + HOUR + 1) is None  # unavailable stays unknown
    assert flow.value_at(T0 + 15 * MIN) == 45.0
    assert history.weather.value_at(T0) == pytest.approx(5.0)
    zone = history.zones["living"].state_at(T0)
    assert zone.temperature == pytest.approx(20.0)
    assert zone.target == pytest.approx(21.0)
    assert zone.valve_open == pytest.approx(0.6)
    assert zone.heating_enabled is True


def test_report_runs_the_core(recorder: Path) -> None:
    mapping = parse_mapping(MAPPING)
    with RecorderDatabase(recorder) as db:
        history = read_history(db, mapping, T0, T0 + 2 * DAY)
    text = report(history, mapping, T0, T0 + 2 * DAY, ZoneInfo("UTC"))
    assert "starts per hour     2.00" in text
    assert "median burn (min)   20.00" in text
    assert "Condensing share:    1.00" in text
    assert "Verdict: not_enough_data" in text


def test_local_days_are_whole_days_inside_the_window() -> None:
    start = 1_780_000_000.0
    days = local_days(start, start + 3 * DAY, ZoneInfo("UTC"))
    assert len(days) == 2
    assert all(end - begin == DAY for begin, end in days)


def test_local_days_follow_the_clock_change() -> None:
    """A day the clocks go forward has 23 hours; any zone with a clock change shows it."""
    tz = ZoneInfo("America/New_York")  # clocks go forward on 2026-03-08
    start = datetime(2026, 3, 7, tzinfo=tz).timestamp()
    days = local_days(start, start + 3 * DAY, tz)
    assert [round((end - begin) / HOUR) for begin, end in days] == [24, 23, 24]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"boiler": {"flame": "binary_sensor.f", "flow": "sensor.f"}, "zones": {"a": "nodot"}},
         "zones"),
        ({"boiler": {"flame": "binary_sensor.f", "flow": "sensor.f"},
          "parameters": {"loss_coefficient": "much"}}, "loss_coefficient"),
        ({"boiler": {"flame": "binary_sensor.f", "flow": "sensor.f"},
          "parameters": {"loss_coefficient": 99}}, "loss_coefficient"),
        ({"boiler": {"flame": "binary_sensor.f", "flow": "sensor.f"},
          "options": {"modulation_scale": "sideways"}}, "modulation_scale"),
        ({"boiler": {"flame": "binary_sensor.f", "flow": "sensor.f"}, "weather": "weather.x"},
         "weather"),
    ],
)  # fmt: skip
def test_a_broken_mapping_is_explained(data: dict, message: str) -> None:
    """P103: every broken part of the mapping gives a message, not a traceback."""
    with pytest.raises(MappingError, match=message):
        parse_mapping(data)


def test_cli(recorder: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mapping_file = tmp_path / "mapping.toml"
    mapping_file.write_text(
        '[boiler]\nflame = "binary_sensor.test_flame"\nflow = "sensor.test_flow"\n'
        'gas_meter = "sensor.not_recorded"\n'
    )
    assert main(["--db", str(recorder), "--mapping", str(mapping_file)]) == 0
    captured = capsys.readouterr()
    assert "Verdict:" in captured.out
    assert "not in the database: sensor.not_recorded" in captured.err


BASE = {"boiler": {"flame": "binary_sensor.f", "flow": "sensor.f"}}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (BASE | {"zone": {"living": "climate.x"}}, r"\[zone\]"),  # a misspelt section
        (BASE | {"options": {"condensing_retrun": 50}}, "condensing_retrun"),  # a misspelt key
        (BASE | {"weather": {"entity": "weather.x", "unit": "C"}}, "unit"),
        (BASE | {"zones": {"living": "sensor.living"}}, "climate"),
        (BASE | {"options": {"temperature_unit": "C"}}, "temperature_unit"),
        (BASE | {"options": {"condensing_return": 90}}, "condensing_return"),
    ],
)
def test_a_mapping_that_would_be_misread_is_refused(data: dict, message: str) -> None:
    """P103: a misspelt section or key would be silently ignored — no zones, a default
    threshold — so it is refused like any other mistake."""
    with pytest.raises(MappingError, match=message):
        parse_mapping(data)


def _mapping_file(tmp_path: Path, text: str | None = None) -> Path:
    path = tmp_path / "mapping.toml"
    path.write_text(
        text
        if text is not None
        else '[boiler]\nflame = "binary_sensor.test_flame"\nflow = "sensor.test_flow"\n'
    )
    return path


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--tz", "Mars/Olympus_Mons"], "time zone"),
        (["--start", "2026-13-01"], "--start"),
        (["--start", "2026-05-30", "--end", "2026-05-29"], "--end"),
    ],
)
def test_the_cli_explains_bad_arguments(
    recorder: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list, message: str
) -> None:
    mapping = _mapping_file(tmp_path)
    assert main(["--db", str(recorder), "--mapping", str(mapping), *args]) == 2
    err = capsys.readouterr().err
    assert message in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[boiler]\nflame = "binary_sensor.test_flame"\n', "missing required signals: flow"),
        ("[boiler\n", "mapping"),  # not TOML
    ],
)
def test_the_cli_explains_a_broken_mapping(
    recorder: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, message: str
) -> None:
    mapping = _mapping_file(tmp_path, text)
    assert main(["--db", str(recorder), "--mapping", str(mapping)]) == 2
    assert message in capsys.readouterr().err


def test_the_cli_on_an_empty_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = RecorderWriter(tmp_path / "empty.db").close()
    assert main(["--db", str(empty), "--mapping", str(_mapping_file(tmp_path))]) == 1
    assert "holds no states" in capsys.readouterr().err


def test_the_cli_with_a_time_zone_and_dates(
    recorder: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Days start at the time zone's midnight; the report covers the days asked for."""
    args = ["--tz", "Europe/Warsaw", "--start", "2026-05-29", "--end", "2026-05-30"]
    assert main(["--db", str(recorder), "--mapping", str(_mapping_file(tmp_path)), *args]) == 0
    assert "Verdict:" in capsys.readouterr().out


def test_local_days_follow_the_autumn_clock_change() -> None:
    """A day the clocks go back has 25 hours."""
    tz = ZoneInfo("America/New_York")  # clocks go back on 2026-11-01
    start = datetime(2026, 10, 31, tzinfo=tz).timestamp()
    days = local_days(start, start + 3 * DAY + HOUR, tz)
    assert [round((end - begin) / HOUR) for begin, end in days] == [24, 25, 24]


def test_the_example_mapping_is_valid_with_every_line_in_use() -> None:
    """Every key the example documents is one the parser accepts."""
    import re
    import tomllib

    text = (Path(__file__).parents[2] / "tools/mapping.example.toml").read_text(encoding="utf-8")
    assert parse_mapping(tomllib.loads(text)).signals
    used = "\n".join(
        line[2:] if re.match(r"# \w+ = ", line) else line for line in text.splitlines()
    )
    mapping = parse_mapping(tomllib.loads(used))
    assert set(mapping.signals) == set(Signal)
    assert mapping.weather is not None
    assert mapping.zones
