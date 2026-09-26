"""The platform scheduler - what makes `kind: job` mean something.

A team declares `schedule: "0 6 * * MON"` and stops thinking about it. They do not run
cron, they do not write a retry loop, and they do not invent an identity for a run with
no user. Twenty-five teams each solving that badly is the problem this platform exists
to remove.

    python runtime/scheduler/main.py --once      run everything due now (or all, with --all)
    python runtime/scheduler/main.py             loop, checking every 30s

Deliberately simple: cron matching to the minute, no backfill, no distributed locking,
no queue. ADR-005 records why - a fancier scheduler is a component to be paged for, and
nothing here yet justifies one.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLATFORM = HERE.parent.parent
REGISTRY = PLATFORM / "control" / "registry" / "apps.json"


def _field_matches(spec: str, value: int) -> bool:
    if spec == "*":
        return True
    for part in spec.split(","):
        if part.startswith("*/"):
            if value % int(part[2:]) == 0:
                return True
        elif "-" in part:
            low, high = (int(x) for x in part.split("-"))
            if low <= value <= high:
                return True
        elif int(part) == value:
            return True
    return False


def due(schedule: str, at: datetime) -> bool:
    """Five-field cron, UTC. minute hour day month weekday."""
    minute, hour, day, month, weekday = schedule.split()
    return (
        _field_matches(minute, at.minute)
        and _field_matches(hour, at.hour)
        and _field_matches(day, at.day)
        and _field_matches(month, at.month)
        and _field_matches(weekday, (at.weekday() + 1) % 7)   # cron: Sunday is 0
    )


def run(name: str, entry: dict) -> int:
    """Run one job as a child process.

    A separate process on purpose: a job that leaks memory, wedges, or exits hard takes
    nothing else with it, and SIGTERM on shutdown reaches the SDK's drain handler.
    """
    run_id = f"run-{uuid.uuid4().hex[:10]}"
    env = dict(os.environ)
    env.update(
        INSIGHTS_APP_MANIFEST=str(Path(entry["path"]) / "app.yaml"),
        INSIGHTS_APP=name,
        INSIGHTS_RUN_ID=run_id,
    )
    print(f"[scheduler] starting {name} {run_id}", flush=True)
    result = subprocess.run([sys.executable, "src/main.py"], cwd=entry["path"], env=env)
    print(f"[scheduler] {name} {run_id} exit={result.returncode}", flush=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="check once and exit")
    parser.add_argument("--all", action="store_true", help="run every job now, ignoring schedules")
    args = parser.parse_args()

    if not REGISTRY.is_file():
        print("no apps registered - run `insights up` first")
        return 1
    registry = json.loads(REGISTRY.read_text())
    jobs = {n: e for n, e in registry.items() if e.get("kind") == "job"}
    print(f"[scheduler] {len(jobs)} job(s): {', '.join(jobs) or '-'}")

    while True:
        now = datetime.now(timezone.utc)
        for name, entry in jobs.items():
            if args.all or (entry.get("schedule") and due(entry["schedule"], now)):
                run(name, entry)
        if args.once or args.all:
            return 0
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
