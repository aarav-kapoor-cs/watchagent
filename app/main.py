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
    return {"readings": rows}


@app.get("/events")
def events(
    city: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
) -> dict:
    return {"events": storage.recent_events(city, limit)}
