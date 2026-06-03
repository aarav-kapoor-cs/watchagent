# WatchAgent — Weather Monitor & AI Assistant

A Python service that polls live weather for three Canadian cities, decides what
is *notable*, stores readings and events, and exposes them over an HTTP API.

## What this demonstrates

- Backend API development with FastAPI (typed validation, auto OpenAPI docs)
- Persistent storage with SQLite and database-level deduplication
- A background poller that fetches, dedups, and processes readings
- Context-aware event detection (not fixed thresholds) — per-city, per-field
- Dockerised single-container deployment with a persistent volume
- A Cursor engineering setup: rules, scoped agents, and an executable skill
- CI on every push: unit tests (network-mocked) plus a Docker build

## Quick start

```bash
git clone https://github.com/aarav-kapoor-cs/watchagent.git
cd watchagent
cp .env.example .env
docker compose up --build
```

Then, in another terminal:

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/readings?city=Ottawa&limit=5"
curl "http://localhost:8000/events?limit=10"
DATABASE_PATH=./data/watchagent.db python .cursor/skills/analyze.py summary
```

---

## System overview

```
                 ┌──────────────────────────────────────────────┐
                 │                 Docker container               │
                 │                                                │
   Open-Meteo    │   ┌──────────┐   new      ┌──────────────┐     │
   (api.open- ───┼──▶│  Poller  │──readings──▶│   Detector   │     │
    meteo.com)   │   │ (thread) │            │ (event logic)│     │
                 │   └────┬─────┘            └──────┬───────┘     │
                 │        │ store readings          │ store events │
                 │        ▼                          ▼            │
                 │   ┌────────────────────────────────────┐      │
                 │   │        SQLite  (/data volume)        │      │
                 │   │     readings table | events table    │      │
                 │   └────────────────┬───────────────────┘      │
                 │                    │ read                      │
                 │            ┌───────▼────────┐                  │
   client ───────┼───────────▶│  FastAPI API   │                  │
   (curl) :8000  │            │ /health        │                  │
                 │            │ /readings      │                  │
                 │            │ /events        │                  │
                 │            └────────────────┘                  │
                 └──────────────────────────────────────────────┘

   Cursor agent ─────▶ .cursor/skills/analyze.py ─── reads ──▶ SQLite
```

**Flow:** a background poller thread fetches each city on an interval, stores
only readings with a new timestamp (dedup), runs the detector on anything new,
and writes notable events. The FastAPI app reads from the same SQLite database
to serve the three endpoints. An executable analysis skill queries the database
directly for ad-hoc questions.

---

## Setup & run

Requires Docker and Git only.

```bash
git clone <your-repo>
cd watchagent
cp .env.example .env
docker compose up --build
```

The API is then reachable at `http://localhost:8000`. The poller begins
collecting immediately. The SQLite database is stored on a named Docker volume
(`watchagent-data`) and persists across `docker compose down` / `up`.

All configuration is via environment variables documented in `.env.example`.
Open-Meteo requires no key, so the project has **no secrets** — nothing
sensitive is ever committed.

---

## API reference

### `GET /health`
```bash
curl http://localhost:8000/health
```
```json
{ "status": "ok", "readings_stored": 42, "events_stored": 3 }
```

### `GET /readings`
Optional `city` filter and `limit` (default 50, most recent first).
```bash
curl "http://localhost:8000/readings?city=Ottawa&limit=50"
```
```json
{ "readings": [ { "id": 42, "city": "Ottawa", "observed_at": "...",
  "temperature": 21.3, "apparent_temp": 20.1, "precipitation": 0.0,
  "wind_speed": 9.0, "weather_code": 1, "fetched_at": "..." } ] }
```

### `GET /events`
Optional `city` filter and `limit` (default 50, most recent first).
```bash
curl "http://localhost:8000/events?city=Ottawa&limit=50"
```
```json
{ "events": [ { "id": 3, "city": "Ottawa", "event_type": "anomaly",
  "field": "temperature", "severity": "severe", "value": 30.0,
  "reason": "temperature 30.0 is 9.5x the normal spread above the recent
  average of 18.1 (last 6 readings)", "observed_at": "...",
  "created_at": "..." } ] }
```

Interactive OpenAPI docs are auto-generated at `http://localhost:8000/docs`.

---

## Running the tests

```bash
pip install -r requirements.txt
python -m pytest -q
```

Tests that touch the weather API mock it, so the suite needs no network and no
keys (the same way CI runs it).

---

## Technology choices

- **FastAPI** for the HTTP layer: typed query-parameter validation, automatic
  OpenAPI docs, and minimal boilerplate for an API-shaped deliverable. For three
  read endpoints it gives request validation and self-documentation essentially
  for free.
- **SQLite** for storage: zero-config, single-file, trivially persisted via a
  Docker volume. The data volume here (three cities, hourly readings) is tiny,
  so a server database would be an unjustified operational weight. The dedup
  guarantee is enforced with a `UNIQUE (city, observed_at)` constraint at the
  schema level rather than in application code. WAL mode is enabled so the
  poller thread and API reads don't block each other.
- **A background thread** (not a separate process or cron) for polling: it
  shares the in-process `Storage` instance with the API, keeps the deployment a
  single container, and is sufficient for an hourly-update data source.
- **requests** for the one outbound HTTP call: simple and well understood.

---

## Event detection design — the reasoning

Raw readings on their own answer "what is the weather"; the harder, more useful
question is **"did something change that a person watching these cities would
want to know about?"** A detector that fires on a fixed threshold
(`temperature > 30`) is technically valid but misses the point: 30 °C is an
ordinary summer afternoon in Ottawa, while the same number would be
extraordinary in Vancouver. The threshold ignores *context*, which is exactly
what makes an event notable.

So every detector here judges a reading **against recent history for the same
city**, and treats each field on its own terms. There are four detectors:

**1. Contextual anomaly (temperature, wind).**
For a new reading we compute how far it sits from the mean of the recent window,
measured in units of that field's recent spread — a z-score-like ratio. Two
refinements make it robust:
- The spread is blended with a **per-city baseline** (`temp_std`, `wind_std` in
  `config.py`). Vancouver's temperature is far more stable than Ottawa's, so the
  same absolute swing produces a larger ratio in Vancouver and is more likely to
  be flagged — which matches intuition.
- We take `max(observed_spread, 0.5 × baseline)` as the effective spread, so an
  unusually calm window can't make a trivial wobble look enormous, and we never
  divide by zero.
An anomaly only fires at ratio ≥ 2.2 (severe at ≥ 3.2), so ordinary fluctuation
stays quiet. This selectivity is asserted in the tests.

**2. Rapid change (temperature, wind).**
The jump from the immediately previous reading. A ±5 °C hourly temperature swing
or a ±25 km/h wind swing is notable regardless of the absolute value — a fast
change *is* the signal. Wind and temperature use different thresholds because
they vary on different scales.

**3. Precipitation onset / heavy precip.**
Precipitation is zero most of the time, so its standard deviation is ~0 and a
z-score is meaningless. It's handled **categorically** instead: rain starting
after a dry reading (onset) or a reading at/above 4 mm (heavy) is the event.
This is the clearest example of "each field carries different signal".

**4. Cross-city temperature spread.**
After each poll cycle, if the warmest and coldest of the three cities differ by
≥ 18 °C (severe at ≥ 25 °C), that spread is itself surfaced as a system-level
event attributed to the pseudo-city `ALL`. This is information about the *set*
of cities, not any one of them.

Every event is stored with enough to answer **what happened, in which city,
when, and why** — `event_type`, `field`, `severity`, `value`, a human-readable
`reason`, and the observation timestamp. All thresholds are named constants at
the top of `detector.py` so behaviour is tunable in one place.

**What it deliberately avoids:** firing on every reading, firing on absolute
values alone, and treating all fields identically. The tests encode both
sides — that expected events fire *and* that a stable history produces nothing.

---

## Cursor setup

A committed `.cursor/` folder configures Cursor as the engineering environment
for this project. Each piece is scoped to a real decision in this codebase.

### Rules (`.cursor/rules/`)

- **`resilience-and-logging.md`** — encodes the failure and logging contract:
  a failed fetch for one city must log at WARNING (`poll failed | city=… |
  reason=…`) and never stop the loop; stored events log at INFO in a fixed
  format; dedup is enforced by the DB constraint with insert-and-catch, never a
  read-then-write check; `insert_reading` returning `False` must skip detection.
  These are the exact conventions the poller and storage code follow, so the
  rule keeps future edits consistent with them.

- **`event-detection.md`** — protects the design of the detector: no fixed
  absolute-value thresholds, anomalies must be context-relative and per-city
  normalised, precipitation stays categorical, every event must carry a `reason`,
  thresholds stay as named constants, and any change must keep the
  fire/stay-quiet tests passing.

### Agents (`.cursor/agents/`)

Two scoped agents, each with YAML frontmatter, the exact commands it may run,
project context, and explicit three-tier boundaries (always / ask first / never).

- **`detection-reviewer.md`** — reviews proposed changes to the event-detection
  logic for noise vs missed signal, rejects naive absolute-value thresholds,
  and checks that every event still carries a `reason` and `severity`. It knows
  the four detectors, the per-city normalisation, and where the constants and
  tests live. Boundary: it reviews detection logic and its tests only, and
  declines API/storage/Docker/CI work.

- **`test-runner.md`** — a QA agent that writes and runs unit tests. It enforces
  the rule that any test touching the weather API must mock it (so CI stays
  network- and secret-free) and that a failing test is never deleted to make the
  suite green. Boundary: writes to `tests/` only, never edits `app/` source to
  fit a test, never performs real network I/O in a test.

### Skill (`.cursor/skills/analyze.py`)

An **executable** data-analysis script — a graded deliverable. Given a question
about the stored data it opens the SQLite database, parses readings and events,
and returns structured JSON:

```bash
DATABASE_PATH=./data/watchagent.db python .cursor/skills/analyze.py summary
DATABASE_PATH=./data/watchagent.db python .cursor/skills/analyze.py summary --city Ottawa
DATABASE_PATH=./data/watchagent.db python .cursor/skills/analyze.py trends --city Toronto --field temperature
DATABASE_PATH=./data/watchagent.db python .cursor/skills/analyze.py compare
DATABASE_PATH=./data/watchagent.db python .cursor/skills/analyze.py events --city Vancouver
```

It supports per-city summaries (min/max/mean/std, counts, time range), per-field
trends (net change, direction, range), latest cross-city temperature comparison,
and an event breakdown by type. It is how you query the collected data from
inside Cursor.

---

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every push to `main` with
two jobs:

- **test** — installs dependencies and runs `pytest`. Tests mock the weather
  API, so this needs no network or secrets.
- **build** — runs `docker build`; the image must build with no API keys.

---

## Project layout

```
app/
  config.py          city definitions + tunables
  logging_config.py  shared logger
  weather_client.py  Open-Meteo fetch + normalise
  storage.py         SQLite, dedup, queries
  detector.py        event detection (the core)
  poller.py          background fetch/store/detect loop
  main.py            FastAPI app + endpoints
tests/
  test_dedup.py      same reading twice -> one row
  test_detector.py   firing + staying-quiet assertions
  test_api.py        endpoint shapes
.cursor/
  rules/             two project rules
  agents/            detection-reviewer + test-runner agents
  skills/analyze.py  executable analysis skill
Dockerfile  docker-compose.yml  .env.example  .github/workflows/ci.yml
```
