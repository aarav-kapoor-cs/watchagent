"""Deduplication test.

Mocks the weather API to return the SAME reading twice and asserts only one
row is stored. The challenge requires this exact scenario.
"""
from __future__ import annotations

from unittest.mock import patch

from app.poller import Poller
from app.storage import Storage


def _fake_reading(city_name: str, temp: float = 20.0):
    return {
        "city": city_name,
        "observed_at": "2026-06-02T14:00",
        "temperature": temp,
        "apparent_temp": temp - 1,
        "precipitation": 0.0,
        "wind_speed": 10.0,
        "weather_code": 1,
        "fetched_at": "2026-06-02T14:01:00+00:00",
    }


def test_same_reading_twice_stored_once(tmp_path):
    storage = Storage(path=str(tmp_path / "t.db"))
    poller = Poller(storage)

    # Always return the identical reading regardless of which city is requested.
    with patch("app.poller.fetch_current", side_effect=lambda c: _fake_reading(c.name)):
        poller.poll_once()
        poller.poll_once()  # second cycle sees the same timestamps

    # Three cities, each polled twice, but each (city, observed_at) is unique once.
    assert storage.count_readings() == 3
    ottawa = storage.recent_readings("Ottawa", 50)
    assert len(ottawa) == 1


def test_cross_city_not_re_emitted_on_duplicate_polls(tmp_path):
    """A persistent cross-city spread must surface exactly once, not once per poll.

    The poller fires far more often than the upstream data updates, so repeated
    cycles see the same (city, observed_at) readings. Per-reading detection is
    skipped on those duplicates; cross-city detection must be skipped too, or the
    events table fills with identical cross_city_spread rows that bury genuinely
    distinct events in /events.
    """
    storage = Storage(path=str(tmp_path / "t.db"))
    poller = Poller(storage)

    # Wide, persistent spread (Ottawa 32 vs Vancouver 8 -> 24C >= severe).
    temps = {"Ottawa": 32.0, "Toronto": 28.0, "Vancouver": 8.0}

    with patch(
        "app.poller.fetch_current",
        side_effect=lambda c: _fake_reading(c.name, temp=temps[c.name]),
    ):
        for _ in range(5):  # five cycles, identical hourly data each time
            poller.poll_once()

    cross = [e for e in storage.recent_events(None, 100)
             if e["event_type"] == "cross_city_spread"]
    # The spread is real, so it should fire once — but only once for this hour.
    assert len(cross) == 1, f"expected 1 cross_city event, got {len(cross)}"
