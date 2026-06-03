#!/usr/bin/env python3
"""WatchAgent data-analysis skill.

An executable tool the Cursor agent (or you) can invoke to ask questions of the
collected data. It opens the SQLite database directly, parses readings and
events, runs analysis, and prints a structured JSON answer.

This is a GRADED deliverable: it must run and produce results.

USAGE
-----
    python .cursor/skills/analyze.py summary
    python .cursor/skills/analyze.py summary --city Ottawa
    python .cursor/skills/analyze.py trends --city Toronto --field temperature
    python .cursor/skills/analyze.py compare
    python .cursor/skills/analyze.py events --city Vancouver

Set DATABASE_PATH to point at the DB (defaults to /data/watchagent.db, the
in-container path; locally pass e.g. DATABASE_PATH=./data/watchagent.db). All
output is JSON on stdout so an agent can parse it.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from statistics import mean, pstdev

DB = os.getenv("DATABASE_PATH", "/data/watchagent.db")
CITIES = ["Ottawa", "Toronto", "Vancouver"]


def _conn() -> sqlite3.Connection:
    if not os.path.exists(DB):
        print(json.dumps({"error": f"database not found at {DB}",
                          "hint": "set DATABASE_PATH or run the stack first"}))
        sys.exit(1)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def _floats(rows, field):
    out = []
    for r in rows:
        v = r[field]
        if v is not None:
            out.append(float(v))
    return out


def summary(conn, city=None):
    cities = [city] if city else CITIES
    result = {}
    for c in cities:
        rows = conn.execute(
            "SELECT * FROM readings WHERE city=? ORDER BY observed_at", (c,)
        ).fetchall()
        ev = conn.execute(
            "SELECT COUNT(*) n FROM events WHERE city=?", (c,)
        ).fetchone()["n"]
        temps = _floats(rows, "temperature")
        winds = _floats(rows, "wind_speed")
        result[c] = {
            "readings": len(rows),
            "events": ev,
            "temperature": _stats(temps),
            "wind_speed": _stats(winds),
            "first_observed": rows[0]["observed_at"] if rows else None,
            "last_observed": rows[-1]["observed_at"] if rows else None,
        }
    return result


def _stats(values):
    if not values:
        return None
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "mean": round(mean(values), 2),
        "std": round(pstdev(values), 2) if len(values) > 1 else 0.0,
        "n": len(values),
    }


def trends(conn, city, field):
    rows = conn.execute(
        f"SELECT observed_at, {field} v FROM readings WHERE city=? "
        "ORDER BY observed_at", (city,)
    ).fetchall()
    series = [(r["observed_at"], r["v"]) for r in rows if r["v"] is not None]
    if len(series) < 2:
        return {"city": city, "field": field, "note": "not enough data"}
    first, last = series[0][1], series[-1][1]
    vals = [v for _, v in series]
    return {
        "city": city,
        "field": field,
        "points": len(series),
        "start_value": round(float(first), 2),
        "end_value": round(float(last), 2),
        "net_change": round(float(last) - float(first), 2),
        "range": round(max(vals) - min(vals), 2),
        "direction": "rising" if last > first else "falling" if last < first else "flat",
    }


def compare(conn):
    """Compare the latest temperature across cities (time-window comparison)."""
    latest = {}
    for c in CITIES:
        row = conn.execute(
            "SELECT temperature, observed_at FROM readings WHERE city=? "
            "ORDER BY observed_at DESC LIMIT 1", (c,)
        ).fetchone()
        if row and row["temperature"] is not None:
            latest[c] = {"temperature": float(row["temperature"]),
                         "observed_at": row["observed_at"]}
    if len(latest) < 2:
        return {"note": "need at least two cities with data"}
    temps = {c: d["temperature"] for c, d in latest.items()}
    warmest = max(temps, key=temps.get)
    coldest = min(temps, key=temps.get)
    return {
        "latest_by_city": latest,
        "warmest": warmest,
        "coldest": coldest,
        "spread": round(temps[warmest] - temps[coldest], 2),
    }


def events(conn, city=None):
    if city:
        rows = conn.execute(
            "SELECT * FROM events WHERE city=? ORDER BY observed_at DESC LIMIT 50",
            (city,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY observed_at DESC LIMIT 50"
        ).fetchall()
    by_type = {}
    for r in rows:
        by_type[r["event_type"]] = by_type.get(r["event_type"], 0) + 1
    return {
        "total": len(rows),
        "by_type": by_type,
        "most_recent": [dict(r) for r in rows[:10]],
    }


def main():
    p = argparse.ArgumentParser(description="WatchAgent data analysis")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summary"); s.add_argument("--city")
    t = sub.add_parser("trends")
    t.add_argument("--city", required=True)
    t.add_argument("--field", default="temperature",
                   choices=["temperature", "wind_speed", "precipitation", "apparent_temp"])
    sub.add_parser("compare")
    e = sub.add_parser("events"); e.add_argument("--city")

    args = p.parse_args()
    conn = _conn()
    if args.cmd == "summary":
        out = summary(conn, args.city)
    elif args.cmd == "trends":
        out = trends(conn, args.city, args.field)
    elif args.cmd == "compare":
        out = compare(conn)
    elif args.cmd == "events":
        out = events(conn, args.city)
    else:
        out = {"error": "unknown command"}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
