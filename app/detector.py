"""Event detection — the core of WatchAgent.

DESIGN PHILOSOPHY (also explained in the README)
-------------------------------------------------
A naive detector fires when a value crosses a fixed threshold (e.g. temp > 30).
The challenge explicitly calls that "intellectually shallow", and it is: 30C is a
hot day in Ottawa but the threshold ignores *context*. 18C in Vancouver in
January is far more notable than 30C in Ottawa in July, because the question that
matters to someone monitoring conditions is "did something change?", not "is the
number big?".

So this detector judges each new reading against the recent history for that
same city, and normalises by how variable that city normally is. The detectors
are:

1. ANOMALY (temperature, wind):
   How far is this reading from the recent mean, measured in units of that
   field's recent spread (a z-score-like ratio)? We also divide by the city's
   configured baseline variability so the same swing is judged in context.
   This fires *selectively* — a reading that is merely a bit above average does
   not qualify; it must stand clearly outside recent behaviour.

2. RAPID CHANGE (temperature, wind):
   The jump from the immediately previous reading. A 6-degree swing in one hour
   is notable regardless of the absolute value. Wind and temperature use
   different thresholds because they behave differently.

3. PRECIPITATION ONSET:
   Precipitation is near-zero most of the time, so a z-score is the wrong tool
   (the std is ~0). Instead we treat it categorically: rain starting after a dry
   spell, or a heavy-rain reading, is the event.

4. FEELS-LIKE GAP (apparent vs actual temperature):
   When the apparent temperature diverges sharply from the actual temperature
   (wind chill or humidity), how it *feels* is the notable fact, not the number
   on the thermometer.

5. CROSS-CITY SPREAD:
   When the warmest and coldest of the three cities differ by an unusually large
   margin at the same time, that itself is worth surfacing — it is a fact about
   the system, not any single city.

Each detector returns at most one event per reading per type, tagged with a
severity, a short summary, and a human-readable reason, so the /events endpoint
can answer "what happened, where, when, and why we thought it mattered".
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any, Optional

from .config import CITIES, DETECTION_WINDOW
from .logging_config import get_logger

log = get_logger("detector")

# Tuning constants. Documented in the README; deliberately conservative so the
# detector fires selectively rather than constantly.
ANOMALY_RATIO = 2.2        # how many "normalised sigmas" before a reading is anomalous
SEVERE_ANOMALY_RATIO = 3.2
TEMP_RAPID_DELTA = 5.0     # deg C change vs previous reading
WIND_RAPID_DELTA = 25.0    # km/h change vs previous reading
PRECIP_HEAVY = 4.0         # mm in the preceding hour = heavy
FEELS_LIKE_GAP = 6.0       # deg C between apparent and actual temperature
FEELS_LIKE_SEVERE = 10.0
CROSS_CITY_SPREAD = 18.0   # deg C between warmest and coldest city
CROSS_CITY_SEVERE = 25.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def detect_for_reading(
    reading: dict[str, Any],
    history: list[dict[str, Any]],
    reading_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return notable events for a single new reading.

    ``history`` is the recent readings for the same city, newest first, NOT
    including the new reading. May be empty (cold start) — in that case only
    detectors that need no history can fire. ``reading_id`` links each event
    back to the stored reading that triggered it.
    """
    events: list[dict[str, Any]] = []
    city_name = reading["city"]
    city = CITIES.get(city_name)
    observed_at = reading["observed_at"]

    window = history[:DETECTION_WINDOW]

    # --- 1. anomaly vs recent history, per field ---
    for field, baseline_std in (
        ("temperature", city.temp_std if city else 2.0),
        ("wind_speed", city.wind_std if city else 7.0),
    ):
        value = _safe_float(reading.get(field))
        if value is None or len(window) < 3:
            continue
        past = [_safe_float(r.get(field)) for r in window]
        past = [p for p in past if p is not None]
        if len(past) < 3:
            continue
        avg = mean(past)
        spread = pstdev(past)
        # Blend the observed spread with the city baseline so a freakishly calm
        # window doesn't make a small change look enormous (avoids div-by-zero too).
        effective_spread = max(spread, baseline_std * 0.5)
        ratio = abs(value - avg) / effective_spread
        if ratio >= ANOMALY_RATIO:
            severe = ratio >= SEVERE_ANOMALY_RATIO
            direction = "above" if value > avg else "below"
            events.append(
                {
                    "city": city_name,
                    "event_type": "anomaly",
                    "field": field,
                    "severity": "severe" if severe else "moderate",
                    "value": round(value, 2),
                    "summary": f"{field} unusually {direction} recent average",
                    "reason": (
                        f"{field} {value:.1f} is {ratio:.1f}x the normal spread "
                        f"{direction} the recent average of {avg:.1f} "
                        f"(last {len(past)} readings)"
                    ),
                    "observed_at": observed_at,
                    "created_at": _now(),
                    "reading_id": reading_id,
                }
            )

    # --- 2. rapid change vs the immediately previous reading ---
    if window:
        prev = window[0]
        for field, delta_threshold in (
            ("temperature", TEMP_RAPID_DELTA),
            ("wind_speed", WIND_RAPID_DELTA),
        ):
            value = _safe_float(reading.get(field))
            prev_value = _safe_float(prev.get(field))
            if value is None or prev_value is None:
                continue
            delta = value - prev_value
            if abs(delta) >= delta_threshold:
                events.append(
                    {
                        "city": city_name,
                        "event_type": "rapid_change",
                        "field": field,
                        "severity": "moderate",
                        "value": round(value, 2),
                        "summary": f"rapid {field} change ({delta:+.1f})",
                        "reason": (
                            f"{field} changed {delta:+.1f} since the previous "
                            f"reading ({prev_value:.1f} -> {value:.1f})"
                        ),
                        "observed_at": observed_at,
                        "created_at": _now(),
                        "reading_id": reading_id,
                    }
                )

    # --- 3. precipitation onset / heavy precip (categorical, not z-score) ---
    precip = _safe_float(reading.get("precipitation"))
    if precip is not None and precip > 0:
        prev_precip = None
        if window:
            prev_precip = _safe_float(window[0].get("precipitation"))
        onset = prev_precip is not None and prev_precip == 0
        heavy = precip >= PRECIP_HEAVY
        if onset or heavy:
            events.append(
                {
                    "city": city_name,
                    "event_type": "precipitation",
                    "field": "precipitation",
                    "severity": "severe" if heavy else "moderate",
                    "value": round(precip, 2),
                    "summary": (
                        "heavy precipitation" if heavy else "precipitation onset"
                    ),
                    "reason": (
                        f"heavy precipitation {precip:.1f} mm"
                        if heavy
                        else f"precipitation started ({precip:.1f} mm) after a dry spell"
                    ),
                    "observed_at": observed_at,
                    "created_at": _now(),
                    "reading_id": reading_id,
                }
            )

    # --- 4. feels-like gap: apparent vs actual temperature ---
    temp = _safe_float(reading.get("temperature"))
    apparent = _safe_float(reading.get("apparent_temp"))
    if temp is not None and apparent is not None:
        gap = apparent - temp
        if abs(gap) >= FEELS_LIKE_GAP:
            severe = abs(gap) >= FEELS_LIKE_SEVERE
            descriptor = "colder" if gap < 0 else "warmer"
            events.append(
                {
                    "city": city_name,
                    "event_type": "feels_like_gap",
                    "field": "apparent_temp",
                    "severity": "severe" if severe else "moderate",
                    "value": round(apparent, 2),
                    "summary": f"feels {abs(gap):.1f}C {descriptor} than actual",
                    "reason": (
                        f"apparent temperature {apparent:.1f} is {abs(gap):.1f}C "
                        f"{descriptor} than the actual {temp:.1f}"
                    ),
                    "observed_at": observed_at,
                    "created_at": _now(),
                    "reading_id": reading_id,
                }
            )

    return events


def detect_cross_city(latest_by_city: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect an unusually large temperature spread across the three cities.

    Called after a poll cycle with the latest reading from each city. This is a
    system-level event, so it is attributed to the special city name 'ALL'.
    """
    temps: dict[str, float] = {}
    for name, reading in latest_by_city.items():
        t = _safe_float(reading.get("temperature"))
        if t is not None:
            temps[name] = t
    if len(temps) < 2:
        return []

    warmest = max(temps, key=temps.get)
    coldest = min(temps, key=temps.get)
    spread = temps[warmest] - temps[coldest]
    if spread < CROSS_CITY_SPREAD:
        return []

    return [
        {
            "city": "ALL",
            "event_type": "cross_city_spread",
            "field": "temperature",
            "severity": "severe" if spread >= CROSS_CITY_SEVERE else "moderate",
            "value": round(spread, 2),
            "summary": f"{spread:.1f}C temperature spread across cities",
            "reason": (
                f"{spread:.1f}C spread across cities: {warmest} {temps[warmest]:.1f} "
                f"vs {coldest} {temps[coldest]:.1f}"
            ),
            "observed_at": max(r["observed_at"] for r in latest_by_city.values()),
            "created_at": _now(),
            "reading_id": None,
        }
    ]
