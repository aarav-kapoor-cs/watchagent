"""Open-Meteo client.

Fetches current conditions for one city and normalises the response into the
internal reading dict. Network and shape errors are turned into a single
``WeatherFetchError`` so the poller has one thing to catch and log.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from .config import HTTP_TIMEOUT_SECONDS, OPEN_METEO_URL, City
from .logging_config import get_logger

log = get_logger("weather_client")

_CURRENT_FIELDS = (
    "temperature_2m,apparent_temperature,precipitation,wind_speed_10m,weather_code"
)


class WeatherFetchError(Exception):
    """Raised when a city's weather cannot be fetched or parsed."""


def fetch_current(city: City) -> dict[str, Any]:
    """Fetch and normalise current conditions for ``city``.

    Returns a reading dict with keys: city, latitude, longitude, observed_at,
    temperature, apparent_temp, precipitation, wind_speed, weather_code,
    fetched_at.
    ``observed_at`` is the API's own timestamp and is what we dedup on.
    """
    params = {
        "latitude": city.latitude,
        "longitude": city.longitude,
        "current": _CURRENT_FIELDS,
        "wind_speed_unit": "kmh",
        "timezone": "auto",
    }
    try:
        resp = requests.get(
            OPEN_METEO_URL, params=params, timeout=HTTP_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherFetchError(str(exc)) from exc

    current = payload.get("current")
    if not current or "time" not in current:
        raise WeatherFetchError("response missing 'current' block")

    return {
        "city": city.name,
        "latitude": city.latitude,
        "longitude": city.longitude,
        "observed_at": current["time"],
        "temperature": current.get("temperature_2m"),
        "apparent_temp": current.get("apparent_temperature"),
        "precipitation": current.get("precipitation"),
        "wind_speed": current.get("wind_speed_10m"),
        "weather_code": current.get("weather_code"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
