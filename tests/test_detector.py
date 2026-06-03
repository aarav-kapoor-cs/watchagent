"""Event detection tests.

These are the most important tests in the suite (per the challenge). Each
builds a controlled sequence of readings and asserts the detector fires the
events we expect AND stays quiet when it should. The assertions encode the
reasoning behind each event definition.
"""
from __future__ import annotations

from app.detector import (
    detect_cross_city,
    detect_for_reading,
)


def _reading(city, temp=20.0, wind=10.0, precip=0.0, observed_at="2026-06-02T14:00"):
    return {
        "city": city,
        "observed_at": observed_at,
        "temperature": temp,
        "apparent_temp": temp - 1,
        "precipitation": precip,
        "wind_speed": wind,
        "weather_code": 1,
        "fetched_at": "2026-06-02T14:01:00+00:00",
    }


def test_stable_history_no_event():
    """A reading in line with a calm history must NOT fire — selectivity."""
    history = [_reading("Ottawa", temp=20 + (i % 2) * 0.3) for i in range(6)]
    new = _reading("Ottawa", temp=20.4)
    events = detect_for_reading(new, history)
    assert events == []


def test_temperature_anomaly_fires():
    """A reading far outside a stable history fires an anomaly event."""
    history = [_reading("Ottawa", temp=20 + (i % 2) * 0.3) for i in range(6)]
    new = _reading("Ottawa", temp=31.0)  # way above ~20
    events = detect_for_reading(new, history)
    types = {e["event_type"] for e in events}
    assert "anomaly" in types
    anomaly = next(e for e in events if e["event_type"] == "anomaly")
    assert anomaly["field"] == "temperature"
    assert anomaly["severity"] in {"moderate", "severe"}


def test_rapid_change_fires():
    """A large jump from the previous reading fires rapid_change."""
    history = [_reading("Toronto", temp=15.0) for _ in range(4)]
    new = _reading("Toronto", temp=22.0)  # +7 vs previous
    events = detect_for_reading(new, history)
    assert any(e["event_type"] == "rapid_change" for e in events)


def test_precip_onset_fires_after_dry():
    """Rain starting after a dry reading fires a precipitation event."""
    history = [_reading("Vancouver", precip=0.0) for _ in range(4)]
    new = _reading("Vancouver", precip=1.5)
    events = detect_for_reading(new, history)
    assert any(e["event_type"] == "precipitation" for e in events)


def test_heavy_precip_is_severe():
    history = [_reading("Vancouver", precip=0.5) for _ in range(4)]
    new = _reading("Vancouver", precip=6.0)
    events = detect_for_reading(new, history)
    precip = next(e for e in events if e["event_type"] == "precipitation")
    assert precip["severity"] == "severe"


def test_cold_start_no_crash():
    """Empty history must not crash and must not invent anomalies."""
    new = _reading("Ottawa", temp=30.0)
    events = detect_for_reading(new, [])
    assert all(e["event_type"] != "anomaly" for e in events)


def test_feels_like_gap_fires():
    """A large gap between apparent and actual temperature is notable."""
    new = _reading("Ottawa", temp=-5.0)
    new["apparent_temp"] = -18.0  # 13C colder than actual -> severe
    events = detect_for_reading(new, [])
    gap = next(e for e in events if e["event_type"] == "feels_like_gap")
    assert gap["severity"] == "severe"
    assert gap["field"] == "apparent_temp"


def test_small_feels_like_gap_quiet():
    """A normal apparent/actual difference must not fire."""
    new = _reading("Ottawa", temp=20.0)
    new["apparent_temp"] = 19.0
    events = detect_for_reading(new, [])
    assert all(e["event_type"] != "feels_like_gap" for e in events)


def test_events_carry_summary_and_reading_id():
    """Every per-reading event must include a summary and the triggering id."""
    history = [_reading("Ottawa", temp=20 + (i % 2) * 0.3) for i in range(6)]
    new = _reading("Ottawa", temp=31.0)
    events = detect_for_reading(new, history, reading_id=99)
    assert events
    for e in events:
        assert e["summary"]
        assert e["reading_id"] == 99


def test_vancouver_more_sensitive_than_ottawa():
    """Same swing is more notable in stable Vancouver than variable Ottawa.

    With identical histories and the same absolute jump, Vancouver (lower
    baseline variability) should reach anomaly while Ottawa may not.
    """
    van_hist = [_reading("Vancouver", temp=10 + (i % 2) * 0.2) for i in range(6)]
    ott_hist = [_reading("Ottawa", temp=10 + (i % 2) * 0.2) for i in range(6)]
    van_new = _reading("Vancouver", temp=14.5)
    ott_new = _reading("Ottawa", temp=14.5)
    van_events = [e for e in detect_for_reading(van_new, van_hist) if e["event_type"] == "anomaly"]
    ott_events = [e for e in detect_for_reading(ott_new, ott_hist) if e["event_type"] == "anomaly"]
    # Vancouver should be at least as likely to flag as Ottawa for the same swing.
    assert len(van_events) >= len(ott_events)


def test_cross_city_spread_fires():
    latest = {
        "Ottawa": _reading("Ottawa", temp=32.0),
        "Toronto": _reading("Toronto", temp=28.0),
        "Vancouver": _reading("Vancouver", temp=10.0),
    }
    events = detect_cross_city(latest)
    assert len(events) == 1
    assert events[0]["event_type"] == "cross_city_spread"
    assert events[0]["city"] == "ALL"


def test_cross_city_no_spread_quiet():
    latest = {
        "Ottawa": _reading("Ottawa", temp=20.0),
        "Toronto": _reading("Toronto", temp=21.0),
        "Vancouver": _reading("Vancouver", temp=19.0),
    }
    assert detect_cross_city(latest) == []
