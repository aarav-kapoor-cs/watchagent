"""Event deduplication tests.

The challenge requires that a condition which stays true across poll cycles is
not re-fired forever. Identical events (same city, type, field, observed_at) are
suppressed by a UNIQUE constraint at the storage layer.
"""
from __future__ import annotations

from unittest.mock import patch

from app.poller import Poller
from app.storage import Storage


def _event(observed_at="2026-06-02T14:00"):
    return {
        "city": "Ottawa",
        "event_type": "anomaly",
        "field": "temperature",
        "severity": "moderate",
        "value": 31.0,
        "summary": "temperature unusually above recent average",
        "reason": "test event",
        "observed_at": observed_at,
        "created_at": "2026-06-02T14:01:00+00:00",
        "reading_id": 1,
    }


def test_identical_event_stored_once(tmp_path):
    storage = Storage(path=str(tmp_path / "e.db"))
    assert storage.insert_event(_event()) is True
    assert storage.insert_event(_event()) is False  # suppressed
    assert storage.count_events() == 1


def test_new_timestamp_is_not_suppressed(tmp_path):
    storage = Storage(path=str(tmp_path / "e.db"))
    storage.insert_event(_event(observed_at="2026-06-02T14:00"))
    storage.insert_event(_event(observed_at="2026-06-02T15:00"))
    assert storage.count_events() == 2


def _hot_then_cold(city_name: str):
    """A reading guaranteed to trip the cross-city spread detector."""
    temps = {"Ottawa": 34.0, "Toronto": 30.0, "Vancouver": 8.0}
    return {
        "city": city_name,
        "latitude": 0.0,
        "longitude": 0.0,
        "observed_at": "2026-06-02T14:00",
        "temperature": temps[city_name],
        "apparent_temp": temps[city_name] - 1,
        "precipitation": 0.0,
        "wind_speed": 10.0,
        "weather_code": 1,
        "fetched_at": "2026-06-02T14:01:00+00:00",
    }


def test_cross_city_event_not_repeated_across_cycles(tmp_path):
    """Same readings on two cycles must not store the spread event twice."""
    storage = Storage(path=str(tmp_path / "x.db"))
    poller = Poller(storage)
    with patch("app.poller.fetch_current", side_effect=lambda c: _hot_then_cold(c.name)):
        poller.poll_once()
        poller.poll_once()
    spread = [e for e in storage.recent_events(None, 50)
              if e["event_type"] == "cross_city_spread"]
    assert len(spread) == 1
