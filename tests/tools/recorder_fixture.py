"""A tiny recorder database with the Home Assistant schema subset the importer reads."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id VARCHAR(255));
CREATE TABLE state_attributes (attributes_id INTEGER PRIMARY KEY, hash BIGINT, shared_attrs TEXT);
CREATE TABLE states (
    state_id INTEGER PRIMARY KEY,
    state VARCHAR(255),
    attributes_id INTEGER,
    last_changed_ts FLOAT,
    last_updated_ts FLOAT,
    last_reported_ts FLOAT,
    old_state_id INTEGER,
    metadata_id INTEGER
);
"""


class RecorderWriter:
    """Builds the test database; only tests write, the importer only reads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._db = sqlite3.connect(path)
        self._db.executescript(SCHEMA)
        self._meta: dict[str, int] = {}
        self._attrs: dict[str, int] = {}

    def add(self, entity_id: str, t: float, state: str, attributes: dict[str, Any] | None = None):
        if entity_id not in self._meta:
            cursor = self._db.execute(
                "INSERT INTO states_meta (entity_id) VALUES (?)", (entity_id,)
            )
            self._meta[entity_id] = int(cursor.lastrowid or 0)
        attrs_id = None
        if attributes is not None:
            shared = json.dumps(attributes, sort_keys=True)
            if shared not in self._attrs:
                cursor = self._db.execute(
                    "INSERT INTO state_attributes (hash, shared_attrs) VALUES (?, ?)", (0, shared)
                )
                self._attrs[shared] = int(cursor.lastrowid or 0)
            attrs_id = self._attrs[shared]
        self._db.execute(
            "INSERT INTO states (state, attributes_id, last_changed_ts, last_updated_ts, "
            "last_reported_ts, metadata_id) VALUES (?, ?, ?, ?, ?, ?)",
            (state, attrs_id, t, t, t, self._meta[entity_id]),
        )
        return self

    def close(self) -> Path:
        self._db.commit()
        self._db.close()
        return self.path
