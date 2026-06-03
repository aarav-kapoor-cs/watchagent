"""Background poller.

Runs in its own thread. Each cycle: fetch every city, store new readings,
run per-reading detection on anything new, then run the cross-city detector.
A failed fetch for one city must NOT stop the others or crash the loop —
this is encoded as a rule in .cursor/rules.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from .config import CITIES, DETECTION_WINDOW, POLL_INTERVAL_SECONDS
from .detector import detect_cross_city, detect_for_reading
from .logging_config import get_logger
from .storage import Storage
from .weather_client import WeatherFetchError, fetch_current

log = get_logger("poller")


class Poller:
    def __init__(self, storage: Storage, interval: int = POLL_INTERVAL_SECONDS) -> None:
        self._storage = storage
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="poller", daemon=True)
        self._thread.start()
        log.info("poller started (interval=%ss)", self._interval)

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # never let the loop die
                log.error("unexpected error in poll cycle: %s", exc)
            self._stop.wait(self._interval)

    def poll_once(self) -> None:
        """One full poll cycle. Public so tests can call it directly."""
        latest_by_city: dict[str, dict[str, Any]] = {}
        any_new = False

        for city in CITIES.values():
            try:
                reading = fetch_current(city)
            except WeatherFetchError as exc:
                # Rule: log city + reason at WARNING, keep going, do not raise.
                log.warning("poll failed | city=%s | reason=%s", city.name, exc)
                continue

            latest_by_city[city.name] = reading
            stored = self._storage.insert_reading(reading)
            if not stored:
                # Duplicate timestamp — skip detection, this isn't new information.
                continue

            any_new = True
            history = self._storage.recent_readings(city.name, DETECTION_WINDOW + 1)
            # history includes the row we just stored; drop it for detection.
            history = [r for r in history if r["observed_at"] != reading["observed_at"]]
            for event in detect_for_reading(reading, history):
                self._storage.insert_event(event)
                log.info(
                    "event | %s | %s/%s | %s",
                    event["city"], event["event_type"],
                    event.get("field"), event["severity"],
                )

        # Cross-city detection must only run when at least one city produced a
        # NEW reading this cycle. The poller fires far more often than the
        # upstream data updates (e.g. every 5 min for hourly data), so without
        # this guard a single persistent spread would be re-emitted on every
        # cycle — the same way per-reading detection is skipped on duplicates
        # above. That flooded the events table with identical cross_city_spread
        # rows and buried genuinely distinct events behind them in /events.
        if not any_new:
            return

        for event in detect_cross_city(latest_by_city):
            self._storage.insert_event(event)
            log.info("event | ALL | cross_city_spread | %s", event["severity"])
