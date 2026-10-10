"""Reading a recorder database copy: read-only access, state at start, attributes, WAL warning."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.recorder_db import RecorderDatabase, StateRow

from .recorder_fixture import RecorderWriter


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    writer = RecorderWriter(tmp_path / "home-assistant_v2.db")
    writer.add("sensor.flow", 100.0, "40.0", {"unit_of_measurement": "°C"})
    writer.add("sensor.flow", 200.0, "45.5", {"unit_of_measurement": "°C"})
    writer.add("sensor.flow", 300.0, "unavailable", {})
    writer.add("sensor.flow", 400.0, "50.0", None)
    writer.add("binary_sensor.flame", 150.0, "on", None)
    return writer.close()


def test_states_include_the_one_holding_at_start(db_path: Path) -> None:
    with RecorderDatabase(db_path) as db:
        rows = list(db.states("sensor.flow", 250.0, 500.0))
    assert rows == [
        StateRow(250.0, "45.5", {"unit_of_measurement": "°C"}),
        StateRow(300.0, "unavailable", {}),
        StateRow(400.0, "50.0", {}),
    ]


def test_states_before_any_data_and_other_entities(db_path: Path) -> None:
    with RecorderDatabase(db_path) as db:
        assert [r.t for r in db.states("sensor.flow", 0.0, 150.0)] == [100.0]
        assert list(db.states("sensor.missing", 0.0, 500.0)) == []
        assert db.entity_ids() == {"sensor.flow", "binary_sensor.flame"}
        assert db.span() == (100.0, 400.0)


def test_database_is_opened_read_only(db_path: Path) -> None:
    db = RecorderDatabase(db_path)
    with pytest.raises(sqlite3.OperationalError):
        db._db.execute("DELETE FROM states")
    db.close()
    assert sorted(p.name for p in db_path.parent.iterdir()) == [db_path.name]


def test_wal_warning(db_path: Path) -> None:
    with RecorderDatabase(db_path) as db:
        assert not db.wal_warning
        db_path.with_name(db_path.name + "-wal").write_bytes(b"x")
        assert db.wal_warning


def test_rejects_files_that_are_not_recorder_databases(tmp_path: Path) -> None:
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE x (y INTEGER)").connection.close()
    with pytest.raises(ValueError, match="not a recorder database"):
        RecorderDatabase(other)
    with pytest.raises(FileNotFoundError):
        RecorderDatabase(tmp_path / "missing.db")
