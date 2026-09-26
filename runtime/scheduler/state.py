"""Scheduler run state - the one piece of platform data that genuinely needs a database.

WHY THIS EXISTS, AND WHY IT IS NOT YAML OR JSONL
------------------------------------------------
Most platform state is config: the app registry, the dataset catalog, the grants read.
That belongs in YAML in git, where a change is reviewed in a PR and `git log` answers
"who changed this and when". Telemetry belongs in append-only JSONL, because that is
the shape production has (stdout -> shipper -> immutable store) and evidence you can
edit is not evidence.

Run state is neither. It is mutable, it is written by one process many times a minute,
it has to survive a restart, and correctness depends on two writers never disagreeing.
That is a database, and SQLite is the smallest one that is already on every machine.

WHAT IT MAKES TRUE
------------------
Three things `app.yaml` declares were, until this existed, only true within one process
lifetime:

  concurrency: forbid   was enforced only because run() blocks the loop. Restart the
                        scheduler mid-run and a second run could start beside the first.
  (dedupe)              `last_fired` was an in-memory dict. The tick is 30s and `due()`
                        matches to the minute, so a restart inside the same minute fired
                        the job twice - the exact bug the dict was added to fix.
  run history           "did Monday's 06:00 run actually happen?" was answerable only by
                        grepping logs for an event the job emits *if it gets that far*.

In production this component is an EventBridge Schedule or a Kubernetes CronJob and the
state lives in the scheduler's own store - so this table is the local stand-in for
something that always existed, not a new concept.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS job_runs (
    app           TEXT    NOT NULL,
    scheduled_for TEXT    NOT NULL,   -- the minute this run belongs to, e.g. 2026-09-28T06:00
    run_id        TEXT    NOT NULL,
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,               -- NULL while in flight
    exit_code     INTEGER,            -- NULL if abandoned
    PRIMARY KEY (app, scheduled_for)  -- dedupe is a CONSTRAINT, not a Python dict
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunState:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")   # a reader must not block the writer
        self.conn.executescript(SCHEMA)

    def reap_abandoned(self) -> int:
        """Close out runs left in flight by a previous scheduler process.

        The scheduler runs jobs as child processes and terminates them on shutdown, so
        any run still marked in-flight at startup is dead by definition. Without this,
        one crash leaves a row that says "still running" forever and `concurrency:
        forbid` blocks that job for good - a liveness bug dressed as a safety feature.
        """
        cursor = self.conn.execute(
            "UPDATE job_runs SET finished_at = ? WHERE finished_at IS NULL", (_now(),)
        )
        return cursor.rowcount

    def in_flight(self, app: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM job_runs WHERE app = ? AND finished_at IS NULL LIMIT 1", (app,)
        ).fetchone()
        return row is not None

    def claim(self, app: str, scheduled_for: str, run_id: str) -> bool:
        """Try to claim this minute for this job. False means someone already has it.

        The INSERT either succeeds or violates the primary key. That is the whole
        dedupe: no read-then-write, so two schedulers racing cannot both win.
        """
        try:
            self.conn.execute(
                "INSERT INTO job_runs (app, scheduled_for, run_id, started_at) VALUES (?,?,?,?)",
                (app, scheduled_for, run_id, _now()),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def finish(self, app: str, scheduled_for: str, exit_code: int) -> None:
        self.conn.execute(
            "UPDATE job_runs SET finished_at = ?, exit_code = ? WHERE app = ? AND scheduled_for = ?",
            (_now(), exit_code, app, scheduled_for),
        )

    def history(self, app: str | None = None, limit: int = 20) -> list[dict]:
        sql = ("SELECT app, scheduled_for, run_id, started_at, finished_at, exit_code "
               "FROM job_runs")
        params: tuple = ()
        if app:
            sql += " WHERE app = ?"
            params = (app,)
        sql += " ORDER BY started_at DESC LIMIT ?"
        rows = self.conn.execute(sql, params + (limit,)).fetchall()
        keys = ("app", "scheduled_for", "run_id", "started_at", "finished_at", "exit_code")
        return [dict(zip(keys, row)) for row in rows]

    def close(self) -> None:
        self.conn.close()
