"""Deduplication test.

Mocks the weather API to return the SAME reading twice and asserts only one
row is stored. The challenge requires this exact scenario.
"""
from __future__ import annotations

from unittest.mock import patch

from app.poller import Poller
from app.storage import Storage


def _fake_reading(city_name: str):
    return {
        "city": city_name,
        "observed_at": "2026-06-02T14:00",
        "temperature": 20.0,
        "apparent_temp": 19.0,
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
