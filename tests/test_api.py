"""API shape tests.

Seed the database directly, then assert /health, /readings and /events return
the exact JSON structure the challenge contract specifies (field names included).
"""
import app.main as main  # noqa: E402
from app.storage import Storage  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _seed(storage: Storage):
    storage.insert_reading(
        {
            "city": "Ottawa",
            "latitude": 45.42,
            "longitude": -75.69,
            "observed_at": "2026-06-02T14:00",
            "temperature": 21.0,
            "apparent_temp": 20.0,
            "precipitation": 0.0,
            "wind_speed": 9.0,
            "weather_code": 1,
            "fetched_at": "2026-06-02T14:01:00+00:00",
        }
    )
    storage.insert_event(
        {
            "city": "Ottawa",
            "event_type": "anomaly",
            "field": "temperature",
            "severity": "moderate",
            "value": 21.0,
            "summary": "temperature unusually above recent average",
            "reason": "test event",
            "observed_at": "2026-06-02T14:00",
            "created_at": "2026-06-02T14:01:00+00:00",
            "reading_id": 1,
        }
    )


def _client(tmp_path):
    # Point the module-level storage at a temp DB and disable the live poller.
    test_storage = Storage(path=str(tmp_path / "api.db"))
    _seed(test_storage)
    main.storage = test_storage
    main.poller.start = lambda: None  # don't hit the network during tests
    main.poller.stop = lambda: None
    return TestClient(main.app)


def test_health_shape(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["readings_stored"], int)
    assert isinstance(body["events_stored"], int)


def test_readings_shape(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/readings?city=Ottawa&limit=50")
    assert resp.status_code == 200
    body = resp.json()
    assert "readings" in body
    assert isinstance(body["readings"], list)
    reading = body["readings"][0]
    assert reading["city"] == "Ottawa"
    # Contract field names (Open-Meteo naming, per challenge_brief.md).
    for key in (
        "city",
        "time",
        "temperature_2m",
        "apparent_temperature",
        "precipitation",
        "wind_speed_10m",
        "weather_code",
    ):
        assert key in reading, f"missing contract field: {key}"


def test_events_shape(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/events?city=Ottawa&limit=50")
    assert resp.status_code == 200
    body = resp.json()
    assert "events" in body
    assert isinstance(body["events"], list)
    event = body["events"][0]
    assert event["event_type"] == "anomaly"
    # Contract field names, per challenge_brief.md.
    for key in (
        "city",
        "event_type",
        "time",
        "severity",
        "summary",
        "reason",
        "reading_id",
    ):
        assert key in event, f"missing contract field: {key}"
