# Resilience & Logging Conventions

These rules encode how this codebase handles failures and logs. Follow them on
every change to poller, weather client, or storage code.

## Polling must be fault-tolerant
- A failed weather fetch for ONE city must never stop the others or kill the
  poll loop. Catch `WeatherFetchError` per city, log, and continue to the next.
- The poll loop (`Poller._run`) must catch unexpected exceptions so one bad
  cycle can never terminate the background thread.
- Never call `raise` inside the per-city loop of a poll cycle.

## Logging contract
- Use `app.logging_config.get_logger(<component>)`; never use bare `print`.
- A failed poll logs at WARNING with the city name and the reason, in the form:
  `poll failed | city=<City> | reason=<msg>`.
- A stored notable event logs at INFO in the form:
  `event | <city> | <event_type>/<field> | <severity>`.
- Reserve ERROR for unexpected exceptions, not for expected upstream failures
  like a transient API timeout (those are WARNING).

## Storage contract
- Deduplication is enforced by the `UNIQUE (city, observed_at)` constraint, not
  by read-then-write checks. Insert and catch `IntegrityError`; never SELECT
  first to decide whether to INSERT (it races with the poller).
- `insert_reading` returns a bool: True = newly stored, False = duplicate. The
  poller must skip event detection when it returns False — duplicates are not
  new information.
