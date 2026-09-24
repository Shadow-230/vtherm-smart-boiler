"""Read states from a copy of a Home Assistant recorder database, strictly read-only.

The file is opened with ``mode=ro&immutable=1``: SQLite neither writes nor creates files next to
it. Immutable mode ignores a write-ahead log, so the copy should be taken with Home Assistant
stopped or from a backup; ``wal_warning`` says when a ``-wal`` file sits next to it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class StateRow:
    t: float  # last_updated, seconds since the Unix epoch
    state: str
    attributes: dict[str, Any]


class RecorderDatabase:
    """States of chosen entities from a recorder database copy (schema with ``states_meta``)."""

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)
        self.path = path
        uri = f"file:{quote(str(path.resolve()))}?mode=ro&immutable=1"
        self._db = sqlite3.connect(uri, uri=True)
        tables = {row[0] for row in self._db.execute("SELECT name FROM sqlite_master")}
        if not {"states", "states_meta"} <= tables:
            self._db.close()
            raise ValueError(f"{path}: not a recorder database with states_meta (HA 2023.4+)")
        self._has_attributes_table = "state_attributes" in tables
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(states)")}
        self._legacy_attributes = "attributes" in columns

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> RecorderDatabase:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def wal_warning(self) -> bool:
        """A write-ahead log next to the copy: recent states may be missing."""
        wal = self.path.with_name(self.path.name + "-wal")
        return wal.is_file() and wal.stat().st_size > 0

    def entity_ids(self) -> set[str]:
        return {row[0] for row in self._db.execute("SELECT entity_id FROM states_meta")}

    def span(self) -> tuple[float, float] | None:
        """First and last state time in the database."""
        row = self._db.execute(
            "SELECT MIN(last_updated_ts), MAX(last_updated_ts) FROM states"
        ).fetchone()
        return None if row is None or row[0] is None else (float(row[0]), float(row[1]))

    def states(self, entity_id: str, start: float, end: float) -> Iterator[StateRow]:
        """The state holding at ``start``, then every state row in ``(start, end)``."""
        attrs = "a.shared_attrs" if self._has_attributes_table else "NULL"
        legacy = "s.attributes" if self._legacy_attributes else "NULL"
        join = (
            "LEFT JOIN state_attributes a ON s.attributes_id = a.attributes_id"
            if self._has_attributes_table
            else ""
        )
        base = (
            f"SELECT s.last_updated_ts, s.state, {attrs}, {legacy} FROM states s "
            f"JOIN states_meta m ON s.metadata_id = m.metadata_id {join} "
            "WHERE m.entity_id = ? "
        )
        before = self._db.execute(
            base + "AND s.last_updated_ts <= ? ORDER BY s.last_updated_ts DESC LIMIT 1",
            (entity_id, start),
        ).fetchone()
        if before is not None:
            yield _row(before, at=start)
        for row in self._db.execute(
            base + "AND s.last_updated_ts > ? AND s.last_updated_ts < ? ORDER BY s.last_updated_ts",
            (entity_id, start, end),
        ):
            yield _row(row)


def _row(row: tuple[Any, ...], at: float | None = None) -> StateRow:
    t, state, shared, legacy = row
    raw = shared if shared is not None else legacy
    try:
        attributes = json.loads(raw) if raw else {}
    except TypeError, ValueError:
        attributes = {}
    if not isinstance(attributes, dict):
        attributes = {}
    return StateRow(float(t) if at is None else at, state if state is not None else "", attributes)
