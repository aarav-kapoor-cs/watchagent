# Cursor Agent Review Instructions

Use this file together with `challenge_brief.md`.

## Goal

Review and improve this repository so it fully satisfies the WatchAgent take-home challenge requirements.

Treat `docs/challenge_brief.md` as the source of truth.

## How to Work

1. Inspect the existing repository structure.
2. Read `docs/challenge_brief.md`.
3. Compare the repo against every requirement.
4. Create a gap analysis before editing.
5. Make small, realistic changes.
6. Do not rewrite the whole repo unless it is clearly necessary.
7. Keep the implementation simple, production-minded, and easy to explain.
8. Test after meaningful changes.
9. Create natural commit history with small, logical commits.

## First Response Required

Before editing code, respond with:

```text
Current repo summary:
- ...

Missing or weak areas:
- ...

Implementation plan:
1. ...
2. ...
3. ...

Proposed commit sequence:
1. ...
2. ...
3. ...
```

## Required Review Areas

Check all of these:

### App functionality

- Open-Meteo polling
- Ottawa, Toronto, Vancouver monitored
- Correct weather fields fetched
- Deduplication by city and API timestamp
- Persistent storage
- Notable event detection
- Events include what happened, city, time, and reason

### API

- `GET /health`
- `GET /readings?city=Ottawa&limit=50`
- `GET /events?city=Ottawa&limit=50`
- Correct JSON structure
- Most recent first
- Optional city filter
- Optional limit with default 50

### Docker

- `cp .env.example .env`
- `docker compose up --build`
- API reachable at `http://localhost:8000`
- Poller starts automatically
- Database persists across container restarts
- No credentials committed

### Tests

- Deduplication test with mocked weather API
- Event detection tests with controlled readings
- API shape tests for seeded data
- Tests must not depend on real Open-Meteo calls

### CI

- Runs on every push to main
- Test job passes
- Docker build job passes
- No API keys required

### README

- System overview
- Architecture diagram or ASCII visualization
- Setup instructions
- API reference with curl examples
- Technology choices and justification
- Event detection design and reasoning
- Cursor setup explanation
- Testing instructions
- CI explanation
- Known limitations

### Cursor setup

- `.cursor/rules/` has at least two real project-specific rules
- `.cursor/agents/` has at least one scoped custom agent
- `.cursor/skills/` has at least one executable Python data-analysis skill
- README explains each rule, agent, and skill

## Suggested Implementation Direction

Prefer this simple architecture unless the repo already has a better one:

```text
poller -> Open-Meteo client -> event detector -> database
                                      |
                                      v
                                  HTTP API
                                      |
                                      v
                              Cursor data skill
```

Recommended stack:

- Python 3.11+
- FastAPI for API
- SQLAlchemy or simple sqlite/postgres access layer
- SQLite or Postgres for persistence
- APScheduler, asyncio loop, or separate poller process
- Pytest for tests
- Docker Compose for API + database/poller
- GitHub Actions for CI

## Event Detection Quality Bar

Do not use only one shallow rule like:

```text
temperature > 30
```

Implement multiple defensible rules, for example:

- city-specific wind spike
- sudden temperature swing
- precipitation onset/spike
- feels-like gap
- cross-city contrast

Each event should have:

- `event_type`
- `city`
- `time`
- `severity`
- `summary`
- `reason`
- link/reference to reading

## Cursor Files to Add If Missing

Suggested files:

```text
.cursor/
  rules/
    poller-error-handling.mdc
    event-schema-and-deduplication.mdc
    api-contracts.mdc
  agents/
    event-detection-reviewer.md
  skills/
    analyze_weather_data.py
```

The skill must be executable and produce useful structured output.

## Commit Message Style

Use natural, professional commits:

```text
chore: scaffold weather monitor service
feat: add open-meteo polling client
feat: persist readings with city timestamp deduplication
feat: implement notable weather event detection
feat: expose health readings and events endpoints
docs: document architecture and event detection decisions
chore: add cursor rules agent and analysis skill
test: cover deduplication event detection and api shape
ci: add test and docker build workflow
fix: handle poller retry logging
```

## Final Output Required

After changes, provide:

```text
Summary of changes:
- ...

How to run:
- ...

How to test:
- ...

Challenge checklist:
- [x] ...
- [ ] ...

Remaining risks:
- ...
```
