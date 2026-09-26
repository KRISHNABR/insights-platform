"""The console shows telemetry and never rows.

That is the single property worth pinning. A fleet-wide console that could show tenant
data would be the largest data-exfiltration surface on the platform, and would need its
own access model, audit and review. This one needs none of that - but only for as long
as the claim stays true, which is what these tests are for.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parent.parent


def _load_console():
    """Import runtime/console/main.py by PATH, not by name.

    `runtime/scheduler/main.py` exists too, so a plain `import main` resolves to
    whichever directory reached sys.path first - which passed when this file ran
    alone and errored when the suite ran together. Loading by location has no such
    ordering to get wrong.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "insights_console", PLATFORM / "runtime" / "console" / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    sinks = tmp_path / "sinks"
    sinks.mkdir()
    # A realistic pair of records, including the audit one that carries the most.
    (sinks / "events.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"ts": "2026-09-28T06:00:01Z", "stream": "events", "level": "info",
         "event": "query_executed", "app": "comp-report", "caller": "sp-comp-report",
         "connection": "hr-warehouse", "engine": "databricks-sql", "ms": 12, "rows": 4},
        {"ts": "2026-09-28T06:00:02Z", "stream": "events", "level": "warn",
         "event": "connection_failed", "app": "comp-report", "caller": "sp-comp-report",
         "connection": "hr-warehouse", "engine": "databricks-sql", "kind": "auth"},
    ]) + "\n")
    monkeypatch.setenv("INSIGHTS_SINK_DIR", str(sinks))

    return TestClient(_load_console().app)


def test_the_connections_view_aggregates_health(client):
    rows = client.get("/api/connections").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["queries"] == 1 and row["failures"] == 1
    assert row["failure_kinds"] == {"auth": 1}
    # auth is the tenant's credential; tls and network are ours.
    assert row["likely_owner"] == "tenant"


def test_a_tls_failure_points_at_the_platform(tmp_path, monkeypatch):
    """The routing hint has to work in BOTH directions, or it is just a label that
    always says 'not us'."""
    from fastapi.testclient import TestClient

    sinks = tmp_path / "sinks"
    sinks.mkdir()
    (sinks / "events.jsonl").write_text(json.dumps({
        "ts": "2026-09-28T06:00:03Z", "stream": "events", "level": "warn",
        "event": "connection_failed", "app": "comp-report", "connection": "hr-warehouse",
        "engine": "databricks-sql", "kind": "tls"}) + "\n")
    monkeypatch.setenv("INSIGHTS_SINK_DIR", str(sinks))

    rows = TestClient(_load_console().app).get("/api/connections").json()
    assert rows[0]["likely_owner"] == "platform"


def test_the_console_cannot_reach_tenant_data():
    """The console can only show what the sink holds, and the sink holds shapes.

    Checked at the IMPORT surface rather than by scanning for the word "connect":
    /api/runs legitimately calls sqlite3.connect on the scheduler's own state, which
    is platform data. What must never appear is the SDK's data path - `connect()`,
    the connectors module, or the broker. If someone later wires one in to "make the
    console more useful", this is the test that should stop them.
    """
    import ast

    source = (PLATFORM / "runtime" / "console" / "main.py").read_text()
    tree = ast.parse(source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)

    leaks = {name for name in imported if "insights_sdk" in name or "connectors" in name
             or "broker" in name}
    assert not leaks, f"the console imports the tenant data path: {leaks}"

    # And the only database it opens is the scheduler's, read-only.
    assert 'mode=ro' in source, "the scheduler state must be opened read-only"


def test_the_console_asserts_nothing_about_identity(client):
    """It reads X-Auth-* like any tenant app and trusts the edge, rather than having
    an auth model of its own that could disagree with the platform's."""
    anonymous = client.get("/api/me").json()
    assert anonymous["subject"] == "anonymous" and anonymous["trusted"] is False

    signed_in = client.get("/api/me", headers={
        "x-auth-user": "suraj@corp.example",
        "x-auth-groups": "MG-PLATFORM",
        "x-auth-edge-token": "whatever-the-edge-sent",
    }).json()
    assert signed_in["subject"] == "suraj@corp.example"
    assert signed_in["groups"] == ["MG-PLATFORM"]
