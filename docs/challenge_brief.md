# WatchAgent Challenge Brief

## 1. Objective

Build **WatchAgent: Weather Monitor & AI Assistant**, a Python service that monitors live weather across three Canadian cities, detects notable weather events, stores readings/events, and exposes the data through an HTTP API.

This is an **Infrastructure & AI take-home challenge**. The implementation matters, but the **Cursor setup** is also graded: committed rules, agent(s), and skill(s) must be specific to this project.

## 2. Core Problem

The system should:

1. Poll live weather data for three Canadian cities.
2. Store only new readings for each city.
3. Decide when a weather change or pattern is notable.
4. Store notable events with clear explanations.
5. Expose readings and events through an HTTP API.
6. Run fully through Docker.
7. Include CI, tests, and a committed `.cursor` setup.

There is no single correct event-detection algorithm. The evaluation focuses on whether the logic is thoughtful, defensible, tested, and clearly explained.

## 3. Data Source

Use **Open-Meteo** as the weather API.

Open-Meteo:
- Free
- No account required
- No API key required
- Works from Docker containers

Base request format:

```http
GET https://api.open-meteo.com/v1/forecast
    ?latitude={lat}
    &longitude={lon}
    &current=temperature_2m,apparent_temperature,precipitation,wind_speed_10m,weather_code
    &wind_speed_unit=kmh
    &timezone=auto
```

## 4. Cities to Monitor

| City | Country | Latitude | Longitude |
|---|---:|---:|---:|
| Ottawa | Canada | 45.42 | -75.69 |
| Toronto | Canada | 43.70 | -79.42 |
| Vancouver | Canada | 49.25 | -123.12 |

## 5. Weather Fields

Each API response contains a `current` object with:

- `time`
- `temperature_2m` in Celsius
- `apparent_temperature` in Celsius
- `precipitation` in mm over the preceding hour
- `wind_speed_10m` in km/h
- `weather_code` as WMO integer code

The Open-Meteo API updates readings once per hour. The service may poll more frequently, but it must **only store a reading when the timestamp is new for that city**.

## 6. Required Stored Reading Fields

Each stored reading should include at least:

- city
- latitude
- longitude
- observed timestamp from API
- stored timestamp
- temperature_2m
- apparent_temperature
- precipitation
- wind_speed_10m
- weather_code
- raw/source metadata if useful

## 7. Event Detection Requirements

The system must define and implement its own **notable event detection logic**.

The challenge intentionally does not define exact thresholds. The logic should show reasoning, not just shallow rules.

Good event detection should consider ideas like:

- A single extreme reading may be notable.
- A reading may be notable only compared to previous readings.
- The same temperature change may mean different things in Vancouver than in Ottawa.
- Events should fire selectively and avoid too much noise.
- Weather fields have different meanings: wind, precipitation, and temperature behave differently.
- Cross-city comparisons can be useful.
- Repeated identical events should not fire forever.

Each stored event must answer:

- What happened?
- Which city did it affect?
- When did it happen?
- Why did the system consider it notable?

## 8. Suggested Event Types

These are not required, but are strong options:

### Temperature swing
Detect sudden temperature or apparent-temperature changes compared to previous readings for the same city.

### Feels-like gap
Detect when apparent temperature differs significantly from actual temperature.

### Precipitation onset or spike
Detect when precipitation moves from zero/low to meaningful rainfall or spikes compared to recent readings.

### Wind spike
Detect unusually high wind speed, possibly using city-specific baselines.

### Cross-city contrast
Detect when one city becomes much colder, warmer, wetter, or windier than the others.

### Weather-code transition
Detect meaningful WMO weather-code changes, especially transitions into rain, snow, fog, storm, etc.

## 9. Required API Endpoints

Build an HTTP API in Python. Choose a framework that fits the task and justify it in the README.

The API must expose exactly these endpoint contracts.

### `GET /health`

Response:

```json
{
  "status": "ok",
  "readings_stored": 123,
  "events_stored": 12
}
```

### `GET /readings?city=Ottawa&limit=50`

Response:

```json
{
  "readings": [
    {
      "city": "Ottawa",
      "time": "...",
      "temperature_2m": 10.2,
      "apparent_temperature": 8.9,
      "precipitation": 0.0,
      "wind_speed_10m": 12.3,
      "weather_code": 3
    }
  ]
}
```

Query parameters:

- `city`: optional filter
- `limit`: optional, default `50`
- Return most recent readings first.

### `GET /events?city=Ottawa&limit=50`

Response:

```json
{
  "events": [
    {
      "city": "Ottawa",
      "event_type": "wind_spike",
      "time": "...",
      "severity": "medium",
      "summary": "Wind speed increased sharply",
      "reason": "Wind speed reached 42 km/h, above the city threshold and recent baseline.",
      "reading_id": 123
    }
  ]
}
```

Query parameters:

- `city`: optional filter
- `limit`: optional, default `50`
- Return most recent events first.

## 10. Docker Requirements

The full stack must start on a clean machine with Docker and Git using:

```bash
git clone <your-repo>
cp .env.example .env
docker compose up --build
```

After startup:

- API must be reachable at `http://localhost:8000`
- Poller must automatically begin collecting readings
- Database must persist across container restarts
- `.env.example` must document all required environment variables
- No real credentials should be committed

## 11. Cursor Setup Requirements

The repository must commit a `.cursor` folder. Reviewers will read every file inside it.

The `.cursor` folder must include:

```text
.cursor/
  rules/
  agents/
  skills/
```

### Rules

Create at least **two rule files** under:

```text
.cursor/rules/
```

Rules must encode real project-specific conventions.

Weak rule example:

```text
Write clean, readable code.
```

Strong rule example:

```text
When the poller fails, log city name, HTTP status, and retry count at WARNING level; do not raise unless all retries fail.
```

Good rule topics:

- Poller error handling
- Deduplication rules
- Event schema rules
- Logging conventions
- API response shape
- Database access conventions
- Testing rules for mocked weather API calls

### Agent

Create at least **one custom agent** under:

```text
.cursor/agents/
```

The agent must be scoped to a specific project task and include real system-prompt context.

Good agent ideas:

- `event-detection-reviewer`
- `database-query-reviewer`
- `weather-poller-debugger`
- `test-coverage-reviewer`
- `cursor-setup-auditor`

The agent should have:

- clear name
- purpose
- boundary/scope
- system prompt with project context
- instructions about what it should check and what it should avoid

### Skill

Create at least **one executable Python skill** under:

```text
.cursor/skills/
```

One skill **must be a data analysis script**.

The skill should:

- Run from the command line
- Query stored readings/events from the database
- Answer questions about stored data
- Perform analysis such as trends, per-city comparisons, time-window summaries, anomaly counts, event counts, etc.
- Return structured output

This is a graded deliverable, so it must actually run and produce results.

Good skill examples:

- `analyze_weather_data.py`
- `replay_event_detection.py`
- `scan_deduplication_anomalies.py`
- `summarize_events.py`

## 12. CI Requirements

Use:

- GitHub Actions if hosted on GitHub
- GitLab CI if hosted on GitLab

The pipeline must run on every push to `main`.

It must include two jobs:

### Test job

- Run unit tests.
- Any test that calls the real weather API must mock that call.
- Tests must pass.

### Build job

- Run `docker build`.
- Image must build successfully without API keys.

The CI status on the latest commit to `main` is reviewed.

## 13. Minimum Unit Tests

Write unit tests covering at least:

### Deduplication

Mock the weather API to return the same reading twice and assert only one row is stored.

### Event detection logic

Given controlled sequences of readings, assert that expected events fire and non-events do not fire.

These tests should reflect the reasoning behind the event definitions.

### API shape

Assert `/health`, `/readings`, and `/events` return the correct JSON structure for a seeded dataset.

## 14. README Requirements

README must include:

- System overview
- Architecture diagram or ASCII visualization showing:
  - poller
  - storage/database
  - API
  - Cursor skills
- Setup and run instructions
- API reference with example `curl` commands
- Technology choices with justification
- Event detection design and reasoning
- Cursor Setup section explaining:
  - each rule
  - each agent
  - each skill
  - why each exists
- Testing instructions
- CI explanation
- Known limitations or future improvements

## 15. Submission Requirements

Submit:

1. Public GitHub or GitLab repository link, clonable without special access.
2. Committed `.cursor` folder with rules, agent definition, and skill(s).
3. README covering architecture, setup, API examples, event-detection reasoning, technology choices, and Cursor setup.
4. Passing CI pipeline on `main`.

## 16. Automatic Disqualifiers

Avoid these:

- Credentials committed to repo
- Failing CI pipeline at submission time
- `docker compose up` fails on clean clone
- Database does not persist across container restarts
- Missing committed `.cursor` folder
- Non-functional Cursor skill
- API unavailable at `http://localhost:8000`

## 17. Evaluation Criteria

### Event Detection Design

The logic is thoughtful and defensible. It balances sensitivity and noise. README explains why the definitions were chosen. Unit tests verify the stated logic.

### Python and Architecture

Code is clear, structured, and handles errors. Deduplication is correct. Logging is structured. Project structure is clean. Technology choices are justified. README includes architecture visualization.

### Cursor Setup

Rules enforce real project-specific conventions. Agent has scoped purpose and real project context. Data analysis skill runs, queries stored data, and produces useful output. README explains the reasoning behind each Cursor item.

### Docker, CI, and Tests

Stack starts from clean clone. Database persists. CI is green. Unit tests cover deduplication and event logic.

## 18. Strong Submission Checklist

- [ ] Python 3.11+
- [ ] Open-Meteo polling works
- [ ] Ottawa, Toronto, Vancouver monitored
- [ ] New timestamp deduplication per city
- [ ] Readings stored persistently
- [ ] Notable events stored with reason
- [ ] `GET /health` works
- [ ] `GET /readings` works with city and limit
- [ ] `GET /events` works with city and limit
- [ ] Docker Compose works from clean clone
- [ ] API available at `localhost:8000`
- [ ] Poller starts automatically
- [ ] `.env.example` included
- [ ] No credentials committed
- [ ] `.cursor/rules/` has at least two specific rules
- [ ] `.cursor/agents/` has at least one scoped custom agent
- [ ] `.cursor/skills/` has at least one executable data analysis Python script
- [ ] README explains Cursor setup
- [ ] README explains event detection reasoning
- [ ] Unit tests cover deduplication
- [ ] Unit tests cover event detection
- [ ] Unit tests cover API response shape
- [ ] CI runs tests
- [ ] CI builds Docker image
- [ ] CI is green on `main`
