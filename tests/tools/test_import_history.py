"""History importer: mapping, reading a recorder copy into History, the report and the CLI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom_components.vtherm_smart_boiler.core.daily import fit_points
from custom_components.vtherm_smart_boiler.core.history import History
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


@pytest.mark.parametrize("kind", ["missing", "not sqlite", "no states_meta"])
def test_the_cli_explains_a_bad_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    """PB-88: a missing, non-SQLite or non-recorder ``--db`` ends in the one-line usage error
    (exit 2), not a traceback."""
    db = tmp_path / "db.sqlite"
    if kind == "not sqlite":
        db.write_text("not a database at all, just text\n" * 10, encoding="utf-8")
    elif kind == "no states_meta":
        import sqlite3

        connection = sqlite3.connect(db)
        connection.execute("CREATE TABLE other (x)")
        connection.commit()
        connection.close()
    assert main(["--db", str(db), "--mapping", str(_mapping_file(tmp_path))]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: --db ")
    assert len(err.strip().splitlines()) == 1
    assert "Traceback" not in err


def test_the_cli_on_an_empty_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = RecorderWriter(tmp_path / "empty.db").close()
    assert main(["--db", str(empty), "--mapping", str(_mapping_file(tmp_path))]) == 1
    assert "holds no states" in capsys.readouterr().err


def test_the_cli_with_a_time_zone_and_dates(
    recorder: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Days start at the time zone's midnight; the report covers the days asked for."""
    args = ["--tz", "America/New_York", "--start", "2026-05-29", "--end", "2026-05-30"]
    assert main(["--db", str(recorder), "--mapping", str(_mapping_file(tmp_path)), *args]) == 0
    out = capsys.readouterr().out
    assert "Window: 2026-05-29 00:00 – 2026-05-30 00:00 (1.0 days)" in out
    assert "Verdict:" in out


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


def _steady_heat(start: float, end: float) -> History:
    """A burner on all the time at 50 % modulation (12 kW with the mapping's 4–20 kW boiler),
    5 °C outside."""
    from custom_components.vtherm_smart_boiler.core.series import Series

    return History(
        signals={
            Signal.FLAME: Series([(start, True)]),
            Signal.FLOW: Series([(start, 45.0)]),
            Signal.MODULATION: Series([(start, 50.0)]),
            Signal.DHW_ACTIVE: Series([(start, False)]),
        },
        weather=Series([(start, 5.0)]),
    )


def test_23_and_25_hour_days_are_normalised() -> None:
    """P-93: the importer fitted the building on raw day totals, so the day the clocks go
    forward (23 h) looked colder-weathered and the day they go back (25 h) warmer. Each day is
    summarised as the plugin does and fitted as a whole day."""
    from tools.import_history import day_summaries

    mapping = parse_mapping(MAPPING)
    tz = ZoneInfo("America/New_York")
    for first, hours in (((2026, 3, 7), [24, 23, 24]), ((2026, 10, 31), [24, 25, 24])):
        start = datetime(*first, tzinfo=tz).timestamp()
        end = start + 3 * DAY + HOUR
        days = day_summaries(_steady_heat(start - DAY, end + DAY), mapping, start, end, tz)
        assert [round((d.end - d.start) / HOUR) for d in days] == hours
        assert [d.heat_kwh for d in days] == [pytest.approx(12.0 * h) for h in hours]
        points = fit_points(days)
        assert [p.energy_kwh for p in points] == [pytest.approx(12.0 * 24)] * 3


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--start", "2030-01-01"], "window"),  # after the last state: reversed
        (["--end", "2020-01-01"], "window"),  # before the first state: reversed
    ],
)
def test_a_zero_or_reversed_window_is_refused(
    recorder: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list, message: str
) -> None:
    """P-111: a window that ends where it starts divided by zero; one that ends before it
    starts gave a negative report. Both are refused with a message and exit code 2."""
    mapping = _mapping_file(tmp_path)
    assert main(["--db", str(recorder), "--mapping", str(mapping), *args]) == 2
    err = capsys.readouterr().err
    assert message in err
    assert "Traceback" not in err


def test_the_report_refuses_an_empty_window(recorder: Path) -> None:
    """P-111: the report itself divides by the window's length: an empty or reversed one is an
    error, not a division by zero or a negative report."""
    mapping = parse_mapping(MAPPING)
    with RecorderDatabase(recorder) as db:
        history = read_history(db, mapping, T0, T0 + DAY)
    for end in (T0, T0 - HOUR):
        with pytest.raises(ValueError, match="empty or reversed"):
            report(history, mapping, T0, end, ZoneInfo("UTC"))


def test_a_database_of_one_moment_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """P-111: every state at one moment gives a window of zero length: refused, exit code 2."""
    single = RecorderWriter(tmp_path / "single.db")
    single.add("binary_sensor.test_flame", T0, "off")
    single.add("sensor.test_flow", T0, "30.0", {"unit_of_measurement": "°C"})
    db = single.close()
    assert main(["--db", str(db), "--mapping", str(_mapping_file(tmp_path))]) == 2
    err = capsys.readouterr().err
    assert "window" in err
    assert "Traceback" not in err


def test_each_day_is_summarised_from_its_own_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """A13: every day was summarised over the whole imported history, so the work grew with
    the square of the days. Each day now sees only its own samples, plus twelve hours on each
    side for the burns across midnight."""
    import tools.import_history as importer
    from custom_components.vtherm_smart_boiler.core.daily import summarize_day

    seen: list[tuple[float, float, list[float]]] = []

    def spy(history: History, parameters, start: float, end: float, *args, **kwargs):
        times = [s.t for series in history.signals.values() for s in series]
        times += [s.t for s in history.weather]
        seen.append((start, end, times))
        return summarize_day(history, parameters, start, end, *args, **kwargs)

    monkeypatch.setattr(importer, "summarize_day", spy)
    mapping = parse_mapping(MAPPING)
    tz = ZoneInfo("UTC")
    start = datetime(2026, 1, 10, tzinfo=tz).timestamp()
    end = start + 10 * DAY
    history = _steady_heat(start - DAY, end + DAY)
    flame = history.signals[Signal.FLAME]
    for k in range(int(12 * DAY // HOUR)):  # a change every hour over twelve days
        flame.append(start - DAY + k * HOUR + 1, k % 2 == 0)
    importer.day_summaries(history, mapping, start, end, tz)
    assert len(seen) == 10
    for day_start, day_end, times in seen:
        assert times
        assert min(times) >= day_start - 12 * HOUR
        assert max(times) < day_end + 12 * HOUR
        assert len(times) <= 2 * (day_end - day_start + 24 * HOUR) / HOUR
