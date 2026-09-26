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
def apps(request: Request) -> JSONResponse:
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

    caller_groups = set(_caller(request)["groups"])
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
        allowed = set(entry.get("groups") or ())
        out.append({
            # "mine" = a group you are in may use this app. The console shows
            # everything and marks yours; hiding other teams' apps would make the
            # platform feel smaller than it is and help nobody.
            "mine": bool(caller_groups & allowed) if allowed else True,
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


def _manifest_for(name: str) -> tuple[dict, str]:
    """The app's manifest, parsed and raw.

    Safe to show: the loader refuses a credential anywhere in this file, so there is
    nothing in it to redact. `secret:` is a NAME whose value lives somewhere neither
    this console nor the platform team can read.
    """
    entry = _registered().get(name) or {}
    path = Path(entry.get("path", "")) / "app.yaml"
    if not path.is_file():
        return {}, ""
    raw = path.read_text()
    return (yaml.safe_load(raw) or {}), raw


@app.get("/api/apps/{name}")
def app_detail(name: str, request: Request) -> JSONResponse:
    registry = _registered()
    if name not in registry:
        return JSONResponse({"error": f"no app '{name}'"}, status_code=404)

    entry = registry[name]
    parsed, raw = _manifest_for(name)
    caller = _caller(request)
    groups = set(caller["groups"])
    manage = ((parsed.get("access") or {}).get("manage") or {})

    events = [r for r in _records("events") if r.get("app") == name]
    failures = [r for r in events if r.get("event") == "connection_failed"]
    queries = [r for r in events if r.get("event") == "query_executed"]

    return JSONResponse({
        "name": name,
        "kind": entry.get("kind"),
        "team": entry.get("team"),
        "route": (parsed.get("web") or {}).get("route"),
        "schedule": entry.get("schedule"),
        "port": entry.get("port"),
        "running": bool(entry.get("port")),
        "manifest": raw,
        "connections": [
            {"name": c.get("name"), "engine": c.get("engine") or c.get("type"),
             "secret": c.get("secret"),
             "local": bool(c.get("local"))}
            for c in (parsed.get("connections") or [])
        ],
        "telemetry": {"events": len(events), "queries": len(queries),
                      "failures": len(failures)},
        "recent": sorted(events, key=lambda r: r.get("ts", ""))[-20:],
        # What YOU may do here. The console asserts nothing - it reports what the
        # app's own access.manage says about the groups the edge vouched for.
        "you": {
            "is_owner": bool(groups & set(manage.get("owners") or ())),
            "is_contributor": bool(groups & (set(manage.get("owners") or ())
                                             | set(manage.get("contributors") or ()))),
        },
    })


@app.post("/api/apps/{name}/run")
def run_job(name: str, request: Request) -> JSONResponse:
    """Run a job now. The console's first WRITE endpoint.

    Authorized the same way everything else is: the edge established who you are, and
    `access.manage` in the app's own manifest says whether you may. A contributor or
    an owner may run it; a reader may not - running a job is an action, not a view.
    """
    registry = _registered()
    entry = registry.get(name)
    if entry is None:
        return JSONResponse({"error": f"no app '{name}'"}, status_code=404)
    if entry.get("kind") != "job":
        return JSONResponse({"error": f"'{name}' is not a job"}, status_code=400)

    caller = _caller(request)
    if not caller["trusted"]:
        return JSONResponse({"error": "not signed in"}, status_code=401)

    parsed, _ = _manifest_for(name)
    manage = ((parsed.get("access") or {}).get("manage") or {})
    allowed = set(manage.get("owners") or ()) | set(manage.get("contributors") or ())
    if not (set(caller["groups"]) & allowed):
        return JSONResponse({
            "error": f"{caller['subject']} is not a contributor or owner of '{name}'",
            "hint": "running a job is an action, not a view - readers cannot",
        }, status_code=403)

    import subprocess
    import sys

    started = subprocess.run(
        [sys.executable, "src/main.py"],
        cwd=Path(entry["path"]), capture_output=True, text=True, timeout=120,
        env={**os.environ, "INSIGHTS_APP": name,
             "INSIGHTS_APP_MANIFEST": str(Path(entry["path"]) / "app.yaml")},
    )
    # Return the structured records the run emitted, not its raw stdout - the same
    # rule as everywhere else, and it keeps this endpoint unable to leak a payload.
    records = []
    for line in started.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return JSONResponse({
        "app": name,
        "exit_code": started.returncode,
        "triggered_by": caller["subject"],
        "events": records,
        "stderr": started.stderr.splitlines()[-5:] if started.returncode else [],
    })
