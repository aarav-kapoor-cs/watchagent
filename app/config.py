"""Central configuration for WatchAgent.

All tunable values live here so behaviour can be changed without touching
logic. Values are read from environment variables where it makes sense for
deployment, with sensible defaults for local runs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    """A monitored city and the climate context used to normalise events.

    The ``*_std`` fields express how much day-to-day variation is *normal* for
    that city. Vancouver's temperature is far more stable than Ottawa's, so the
    same absolute swing should not be judged the same way. These are rough,
    deliberately hand-set baselines, documented in the README.
    """

    name: str
    latitude: float
    longitude: float
    temp_std: float  # typical hour-to-hour temperature variation (deg C)
    wind_std: float  # typical wind variation (km/h)


CITIES: dict[str, City] = {
    "Ottawa": City("Ottawa", 45.42, -75.69, temp_std=2.5, wind_std=8.0),
    "Toronto": City("Toronto", 43.70, -79.42, temp_std=2.2, wind_std=7.0),
    "Vancouver": City("Vancouver", 49.25, -123.12, temp_std=1.3, wind_std=5.0),
}

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# How often the poller fetches each city (seconds). The API only updates hourly,
# so we poll more often and rely on timestamp dedup to avoid storing repeats.
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

# Where SQLite lives. Mounted to a Docker volume so it survives restarts.
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/watchagent.db")

# Network timeout for a single poll attempt.
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))

# Number of recent readings the detector looks back over to build context.
DETECTION_WINDOW = int(os.getenv("DETECTION_WINDOW", "6"))
