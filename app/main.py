"""HTTP API.

FastAPI is chosen (justified in README): automatic request validation, typed
query params, built-in OpenAPI docs at /docs, and async-ready — all useful for
an API-shaped deliverable, with very little boilerplate.

Endpoints match the challenge contract exactly:
  GET /health   -> {"status","readings_stored","events_stored"}
  GET /readings -> {"readings":[...]}  (optional ?city, ?limit default 50)
  GET /events   -> {"events":[...]}    (optional ?city, ?limit default 50)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query

from .logging_config import get_logger
from .poller import Poller
from .storage import Storage

log = get_logger("api")

storage = Storage()
poller = Poller(storage)


@asynccontextmanager
async def lifespan(app: FastAPI):
    poller.start()
    yield
    poller.stop()


app = FastAPI(title="WatchAgent", version="1.0.0", lifespan=lifespan)


def _serialize_reading(row: dict) -> dict:
    """Map an internal readings row to the API contract field names.

    Storage uses short internal column names; the challenge contract specifies
    Open-Meteo's names (``time``, ``temperature_2m``, ...). Mapping here keeps
    the database schema decoupled from the public API shape.
    """
    return {
        "city": row["city"],
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "time": row["observed_at"],
        "stored_at": row["fetched_at"],
        "temperature_2m": row.get("temperature"),
        "apparent_temperature": row.get("apparent_temp"),
        "precipitation": row.get("precipitation"),
        "wind_speed_10m": row.get("wind_speed"),
        "weather_code": row.get("weather_code"),
    }


def _serialize_event(row: dict) -> dict:
    """Map an internal events row to the API contract field names."""
    return {
        "city": row["city"],
        "event_type": row["event_type"],
        "field": row.get("field"),
        "time": row["observed_at"],
        "severity": row["severity"],
        "value": row.get("value"),
        "summary": row["summary"],
        "reason": row["reason"],
        "reading_id": row.get("reading_id"),
    }


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "readings_stored": storage.count_readings(),
        "events_stored": storage.count_events(),
    }


@app.get("/readings")
def readings(
    city: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
) -> dict:
    if city:
        rows = storage.recent_readings(city, limit)
    else:
        rows = storage.all_readings(limit)
    return {"readings": [_serialize_reading(r) for r in rows]}


@app.get("/events")
def events(
    city: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
) -> dict:
    rows = storage.recent_events(city, limit)
    return {"events": [_serialize_event(r) for r in rows]}
