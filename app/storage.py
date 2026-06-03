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
    reason      TEXT    NOT NULL,
    observed_at TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_readings_city_time
    ON readings (city, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_city_time
    ON events (city, observed_at DESC);
"""


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

    # ---- readings -------------------------------------------------------

    def insert_reading(self, reading: dict[str, Any]) -> bool:
        """Insert a reading. Returns True if stored, False if it was a duplicate.

        Duplicate detection relies on the UNIQUE(city, observed_at) constraint.
        We catch IntegrityError rather than checking first to avoid a race
        between the SELECT and the INSERT.
        """
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT INTO readings
                       (city, observed_at, temperature, apparent_temp,
                        precipitation, wind_speed, weather_code, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        reading["city"],
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
                return True
            except sqlite3.IntegrityError:
                # Same (city, observed_at) already stored — expected on repeat polls.
                return False

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

    def insert_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO events
                   (city, event_type, field, severity, value, reason,
                    observed_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["city"],
                    event["event_type"],
                    event.get("field"),
                    event["severity"],
                    event.get("value"),
                    event["reason"],
                    event["observed_at"],
                    event["created_at"],
                ),
            )
            self._conn.commit()

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
