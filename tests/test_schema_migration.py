"""Schema migration tests.

The schema gained columns (``latitude``/``longitude`` on readings, ``summary``/
``reading_id`` on events) and an events dedup uniqueness after the first version
shipped. ``CREATE TABLE IF NOT EXISTS`` does not alter an existing table, so a
database persisted across an upgrade (the Docker-volume case the challenge
requires) must be migrated in place. These tests pin that behaviour.
"""
from __future__ import annotations

import sqlite3

from app.storage import Storage

# The schema as it existed before latitude/longitude/summary/reading_id and the
# events dedup uniqueness were introduced.
_OLD_SCHEMA = """
CREATE TABLE readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    temperature REAL, apparent_temp REAL, precipitation REAL,
    wind_speed REAL, weather_code INTEGER, fetched_at TEXT NOT NULL,
    UNIQUE (city, observed_at)
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT NOT NULL, event_type TEXT NOT NULL, field TEXT,
    severity TEXT NOT NULL, value REAL, reason TEXT NOT NULL,
    observed_at TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def _seed_old_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_SCHEMA)
    conn.execute(
        """INSERT INTO readings
           (city, observed_at, temperature, apparent_temp, precipitation,
            wind_speed, weather_code, fetched_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("Ottawa", "2026-06-02T13:00", 20.0, 19.0, 0.0, 10.0, 1,
         "2026-06-02T13:01:00+00:00"),
    )
    # The pre-dedup code fired the same event every poll cycle, so an existing
    # DB can contain duplicate (city, event_type, field, observed_at) rows.
    for _ in range(3):
        conn.execute(
            """INSERT INTO events
               (city, event_type, field, severity, value, reason,
                observed_at, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("Ottawa", "anomaly", "temperature", "moderate", 20.0,
             "old event", "2026-06-02T13:00", "2026-06-02T13:01:00+00:00"),
        )
    conn.commit()
    conn.close()


def _new_reading() -> dict:
    return {
        "city": "Ottawa", "latitude": 45.42, "longitude": -75.69,
        "observed_at": "2026-06-02T14:00", "temperature": 21.0,
        "apparent_temp": 20.0, "precipitation": 0.0, "wind_speed": 10.0,
        "weather_code": 1, "fetched_at": "2026-06-02T14:01:00+00:00",
    }


def test_migration_adds_columns_and_allows_inserts(tmp_path):
    """Opening an old DB with the new code must add columns and accept writes."""
    db = str(tmp_path / "old.db")
    _seed_old_db(db)

    storage = Storage(path=db)  # must not raise while creating the dedup index

    # New-schema insert (latitude/longitude) now succeeds instead of raising
    # OperationalError "table readings has no column named latitude".
    rid = storage.insert_reading(_new_reading())
    assert rid is not None

    # Pre-existing reading is preserved (data persisted across the upgrade).
    assert storage.count_readings() == 2


def test_migration_collapses_duplicate_events(tmp_path):
    """Duplicate events from the old schema collapse to one and stay deduped."""
    db = str(tmp_path / "old.db")
    _seed_old_db(db)

    storage = Storage(path=db)

    # The three identical seeded events collapse to a single row.
    assert storage.count_events() == 1

    # And the uniqueness now suppresses a fresh identical insert.
    stored = storage.insert_event(
        {
            "city": "Ottawa", "event_type": "anomaly", "field": "temperature",
            "severity": "moderate", "value": 20.0,
            "summary": "temperature unusually above recent average",
            "reason": "old event", "observed_at": "2026-06-02T13:00",
            "created_at": "2026-06-02T13:01:00+00:00", "reading_id": None,
        }
    )
    assert stored is False
    assert storage.count_events() == 1


def test_migration_is_idempotent(tmp_path):
    """Running the migration twice (e.g. two restarts) must be a no-op."""
    db = str(tmp_path / "old.db")
    _seed_old_db(db)

    Storage(path=db)
    storage = Storage(path=db)  # second open must not raise

    assert storage.count_events() == 1
    assert storage.insert_reading(_new_reading()) is not None
