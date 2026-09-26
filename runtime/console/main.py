"""The platform console - one read-only view of the fleet.

WHO IT IS FOR
-------------
Both audiences, deliberately. A tenant opens it to answer "is my app alive, did my
job run, why did my connection fail". The platform team opens it to answer the same
question across three hundred apps. Building two of these would mean two things to
keep true.

THE RULE THAT SHAPES IT
-----------------------
**Telemetry, never rows.** It will tell you that comp-report ran a query on
hr-warehouse, that it took 3ms and returned 4 rows, and that a connection failed with
kind=auth. It will not show you a row, a SQL statement or a secret, because none of
those are in the sink to begin with - the console cannot leak what the platform never
collected.

That is what keeps a fleet-wide console from quietly becoming the largest data-
exfiltration surface on the platform. A console that could show tenant data would
need its own access model, its own audit, and its own review; this one needs none of
those, because there is nothing in it to protect beyond "which apps exist".

AUTH
----
None of its own. It registers in the app registry like any tenant app and sits behind
the edge, so it gets the same SSO, the same session cookie and the same group check -
and it reads `X-Auth-*` exactly as a tenant app does. Dogfooding is the point: if the
edge breaks, the tool the platform team would use to diagnose it breaks the same way,
which is a far better bug to have than a console that works when nothing else does.

LATER
-----
Tenant controls - retry a run, rotate a secret binding, pause a schedule. Each one is
a write endpoint behind `require_role`, and the three authorization layers are
already in place. Read-only first, because a console nobody trusts to be safe is one
nobody is allowed to use.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

HERE = Path(__file__).parent
PLATFORM = HERE.parent.parent
REGISTRY = PLATFORM / "control" / "registry"
SINKS = Path(os.environ.get("INSIGHTS_SINK_DIR", PLATFORM / "runtime" / "sinks"))
STATE_DB = PLATFORM / "runtime" / "state" / "scheduler.db"

app = FastAPI(title="insights-console")


def _registered() -> dict:
    for name in ("apps.local.json", "apps.json"):
        path = REGISTRY / name
        if path.is_file():
            return {k: v for k, v in json.loads(path.read_text()).items() if not k.startswith("_")}
    return {}


def _records(stream: str, limit: int = 2000) -> list[dict]:
    path = SINKS / f"{stream}.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text().splitlines()[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue                       # a half-written line during an active run
    return out


def _caller(request: Request) -> dict:
    """Who the edge says this is. The console asserts nothing about identity itself."""
    return {
        "subject": request.headers.get("x-auth-user", "anonymous"),
        "groups": [g for g in request.headers.get("x-auth-groups", "").split(",") if g],
        "trusted": bool(request.headers.get("x-auth-edge-token")),
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "app": "console"}


@app.get("/api/me")
def me(request: Request) -> dict:
    return _caller(request)


@app.get("/api/apps")
def apps() -> JSONResponse:
    """Every registered app, with whatever the telemetry can say about it."""
    registry = _registered()
    events = _records("events")

    last_seen: dict[str, str] = {}
    errors: dict[str, int] = Counter()
    for record in events:
        name = record.get("app")
        if not name:
            continue
        last_seen[name] = max(last_seen.get(name, ""), record.get("ts", ""))
        if record.get("level") in ("warn", "error"):
            errors[name] += 1

    out = []
    for name, entry in sorted(registry.items()):
        manifest_path = Path(entry.get("path", "")) / "app.yaml"
        connections: list[dict] = []
        if manifest_path.is_file():
            raw = yaml.safe_load(manifest_path.read_text()) or {}
            for spec in raw.get("connections") or []:
                connections.append({
                    "name": spec.get("name"),
                    "engine": spec.get("engine") or spec.get("type"),
                    # The NAME of the secret, never a value - there is no value here
                    # to get wrong. The console reads manifests, and manifests hold
                    # references by construction (the loader refuses anything else).
                    "secret": spec.get("secret"),
                })
        out.append({
            "name": name,
            "kind": entry.get("kind"),
            "team": entry.get("team"),
            "groups": entry.get("groups") or [],
            "schedule": entry.get("schedule"),
            "port": entry.get("port"),
            "connections": connections,
            "last_seen": last_seen.get(name),
            "recent_problems": errors.get(name, 0),
        })
    return JSONResponse(out)


@app.get("/api/runs")
def runs() -> JSONResponse:
    """Scheduled-job history, from the scheduler's own state - not from logs.

    Reading this from telemetry would only ever show runs that got far enough to emit
    something, which silently omits exactly the runs someone is looking for.
    """
    if not STATE_DB.is_file():
        return JSONResponse([])
    conn = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT app, scheduled_for, run_id, started_at, finished_at, exit_code "
            "FROM job_runs ORDER BY started_at DESC LIMIT 100"
        ).fetchall()
    finally:
        conn.close()
    keys = ("app", "scheduled_for", "run_id", "started_at", "finished_at", "exit_code")
    out = []
    for row in rows:
        record = dict(zip(keys, row))
        record["status"] = (
            "running" if record["finished_at"] is None
            else "abandoned" if record["exit_code"] is None
            else "ok" if record["exit_code"] == 0
            else "failed"
        )
        out.append(record)
    return JSONResponse(out)


@app.get("/api/connections")
def connections() -> JSONResponse:
    """Connection health across the fleet - the view this platform is actually for.

    Since the platform ships connectors rather than brokering data, "which connections
    are failing, and is it our fault or theirs" is the operational question. `kind`
    answers the second half: auth and not_found are the tenant's, tls and network are
    usually ours.
    """
    tally: dict[tuple, dict] = defaultdict(
        lambda: {"queries": 0, "failures": 0, "rows": 0, "ms_total": 0, "kinds": Counter()}
    )
    for record in _records("events"):
        event = record.get("event")
        if event not in ("query_executed", "connection_failed"):
            continue
        key = (record.get("app"), record.get("connection"), record.get("engine"))
        bucket = tally[key]
        if event == "query_executed":
            bucket["queries"] += 1
            bucket["rows"] += record.get("rows", 0)
            bucket["ms_total"] += record.get("ms", 0)
        else:
            bucket["failures"] += 1
            bucket["kinds"][record.get("kind", "unknown")] += 1

    out = []
    for (app_name, connection, engine), bucket in sorted(tally.items(), key=lambda kv: str(kv[0])):
        out.append({
            "app": app_name,
            "connection": connection,
            "engine": engine,
            "queries": bucket["queries"],
            "failures": bucket["failures"],
            "rows": bucket["rows"],
            "avg_ms": round(bucket["ms_total"] / bucket["queries"], 1) if bucket["queries"] else None,
            "failure_kinds": dict(bucket["kinds"]),
            # Who is likely to have to fix it. Guidance, not a verdict.
            "likely_owner": (
                "platform" if bucket["kinds"] and
                bucket["kinds"].most_common(1)[0][0] in ("tls", "network")
                else "tenant" if bucket["kinds"] else None
            ),
        })
    return JSONResponse(out)


@app.get("/api/logs")
def logs(app_name: str | None = None, stream: str = "events", limit: int = 100) -> JSONResponse:
    records = _records("audit") if stream == "audit" else _records("events")
    if app_name:
        records = [r for r in records if r.get("app") == app_name]
    records.sort(key=lambda r: r.get("ts", ""))
    return JSONResponse(records[-limit:])


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((HERE / "index.html").read_text())
