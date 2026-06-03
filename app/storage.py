"""SQLite storage layer.

Two tables: ``readings`` (raw observations from Open-Meteo) and ``events``
(notable moments the detector decided to surface).

Deduplication is enforced at the database level: a UNIQUE constraint on
(city, observed_at) means storing the same hourly reading twice is impossible
even if the poller sees it on multiple polls. ``insert_reading`` returns whether
a row was actually inserted so the caller can skip detection on duplicates.

SQLite is chosen for this challenge because it is zero-config, persists to a
single file (easy to back with a Docker volume), and the data volume here
(three cities, hourly) is tiny. This is justified in the README.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Optional

from .config import DATABASE_PATH
from .logging_config import get_logger

log = get_logger("storage")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    city          TEXT    NOT NULL,
    latitude      REAL,
    longitude     REAL,
    observed_at   TEXT    NOT NULL,
    temperature   REAL,
    apparent_temp REAL,
    precipitation REAL,
    wind_speed    REAL,
    weather_code  INTEGER,
    fetched_at    TEXT    NOT NULL,
    UNIQUE (city, observed_at)
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    city        TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    field       TEXT,
    severity    TEXT    NOT NULL,
    value       REAL,
    summary     TEXT,
    reason      TEXT    NOT NULL,
    observed_at TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    reading_id  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_readings_city_time
    ON readings (city, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_city_time
    ON events (city, observed_at DESC);
"""

# The events dedup uniqueness is created by the migration (not in _SCHEMA) so it
# can be applied AFTER collapsing any duplicate rows that a pre-dedup database
# may already contain — creating it eagerly would fail on such a database.
#
# Suppresses repeated identical events: the same condition for the same city at
# the same observed timestamp is stored once, not on every poll cycle.
_EVENTS_DEDUP_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_events_dedup "
    "ON events (city, event_type, field, observed_at)"
)

# Columns added after the original schema shipped. CREATE TABLE IF NOT EXISTS is
# a no-op for an already-existing table, so a database created by an earlier
# version (persisted on a Docker volume across upgrades) would otherwise be
# missing these and every insert/serialize would fail. The migration adds them.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "readings": {"latitude": "REAL", "longitude": "REAL"},
    "events": {"summary": "TEXT", "reading_id": "INTEGER"},
}


class Storage:
    """Thread-safe wrapper around a single SQLite connection.

    The poller thread and the API request handlers share one Storage instance,
    so all writes go through a lock. SQLite is configured with WAL mode for
    better read/write concurrency.
    """

    def __init__(self, path: str = DATABASE_PATH) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._migrate()

    # ---- migration ------------------------------------------------------

    def _migrate(self) -> None:
        """Bring an existing database up to the current schema, idempotently.

        ``CREATE TABLE IF NOT EXISTS`` never alters a table that already exists,
        so a database created by an earlier version (and persisted across an
        upgrade via the Docker volume) keeps its old shape. Without this step the
        new code would fail on every write (missing ``latitude``/``longitude``
        columns) and on ``/events`` serialization (missing ``summary``),
        silently halting all data collection. This runs for fresh databases too,
        where every step is a harmless no-op.
        """
        with self._lock:
            for table, columns in _ADDED_COLUMNS.items():
                existing = {
                    row["name"]
                    for row in self._conn.execute(f"PRAGMA table_info({table})")
                }
                for name, decl in columns.items():
                    if name not in existing:
                        self._conn.execute(
                            f"ALTER TABLE {table} ADD COLUMN {name} {decl}"
                        )
            # A pre-dedup database can hold duplicate events; collapse them
            # (keep the earliest id) before enforcing the uniqueness index.
            self._conn.execute(
                """DELETE FROM events
                   WHERE id NOT IN (
                       SELECT MIN(id) FROM events
                       GROUP BY city, event_type, field, observed_at
                   )"""
            )
            self._conn.execute(_EVENTS_DEDUP_INDEX)
            self._conn.commit()

    # ---- readings -------------------------------------------------------

    def insert_reading(self, reading: dict[str, Any]) -> Optional[int]:
        """Insert a reading. Returns the new row id, or None if it was a duplicate.

        Duplicate detection relies on the UNIQUE(city, observed_at) constraint.
        We catch IntegrityError rather than checking first to avoid a race
        between the SELECT and the INSERT. The returned id lets the caller link
        any detected events back to the exact reading that triggered them.
        """
        with self._lock:
            try:
                cur = self._conn.execute(
                    """INSERT INTO readings
                       (city, latitude, longitude, observed_at, temperature,
                        apparent_temp, precipitation, wind_speed, weather_code,
                        fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        reading["city"],
                        reading.get("latitude"),
                        reading.get("longitude"),
                        reading["observed_at"],
                        reading.get("temperature"),
                        reading.get("apparent_temp"),
                        reading.get("precipitation"),
                        reading.get("wind_speed"),
                        reading.get("weather_code"),
                        reading["fetched_at"],
                    ),
                )
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                # Same (city, observed_at) already stored — expected on repeat polls.
                return None

    def recent_readings(self, city: str, limit: int) -> list[dict[str, Any]]:
        """Most recent readings for a city, newest first."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM readings WHERE city = ?
                   ORDER BY observed_at DESC LIMIT ?""",
                (city, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def all_readings(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM readings ORDER BY observed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_reading(self, city: str) -> Optional[dict[str, Any]]:
        rows = self.recent_readings(city, 1)
        return rows[0] if rows else None

    # ---- events ---------------------------------------------------------

    def insert_event(self, event: dict[str, Any]) -> bool:
        """Insert a notable event. Returns True if stored, False if suppressed.

        A repeat of the same (city, event_type, field, observed_at) is dropped by
        the UNIQUE constraint, so a condition that stays true across poll cycles
        is recorded once rather than re-firing forever.
        """
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO events
                       (city, event_type, field, severity, value, summary,
                        reason, observed_at, created_at, reading_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event["city"],
                        event["event_type"],
                        event.get("field"),
                        event["severity"],
                        event.get("value"),
                        event["summary"],
                        event["reason"],
                        event["observed_at"],
                        event["created_at"],
                        event.get("reading_id"),
                    ),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Identical event already recorded for this timestamp — suppress.
                return False

    def recent_events(self, city: Optional[str], limit: int) -> list[dict[str, Any]]:
        with self._lock:
            if city:
                rows = self._conn.execute(
                    """SELECT * FROM events WHERE city = ?
                       ORDER BY observed_at DESC LIMIT ?""",
                    (city, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM events ORDER BY observed_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    # ---- counts (for /health) ------------------------------------------

    def count_readings(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]

    def count_events(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
