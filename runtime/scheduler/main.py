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

# Import the sibling module without assuming how we were started. Run as a script
# its directory IS sys.path[0] and a flat import works - but the SDK's tests import
# this module to exercise `due()`, and then it is not, so a flat import raised
# ModuleNotFoundError and took three passing tests with it. Belt and braces, once.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from state import RunState                                            # noqa: E402

HERE = Path(__file__).resolve().parent
PLATFORM = HERE.parent.parent
REGISTRY = PLATFORM / "control" / "registry" / "apps.json"


#: cron allows three-letter day and month names. The platform's own most sensitive
#: job declares "0 6 * * MON", so not supporting these was not a theoretical gap -
#: the scheduler crashed on its first tick with ValueError: invalid literal for int().
DAY_NAMES = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}
MONTH_NAMES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _as_int(token: str, names: dict[str, int]) -> int:
    token = token.strip().upper()
    if token in names:
        return names[token]
    return int(token)


def _field_matches(spec: str, value: int, names: dict[str, int] | None = None) -> bool:
    names = names or {}
    if spec == "*":
        return True
    for part in spec.split(","):
        if part.startswith("*/"):
            if value % int(part[2:]) == 0:
                return True
        elif "-" in part:
            low, high = (_as_int(x, names) for x in part.split("-"))
            if low <= value <= high:
                return True
        elif _as_int(part, names) == value:
            return True
    return False


def due(schedule: str, at: datetime) -> bool:
    """Five-field cron, UTC. minute hour day month weekday."""
    minute, hour, day, month, weekday = schedule.split()
    return (
        _field_matches(minute, at.minute)
        and _field_matches(hour, at.hour)
        and _field_matches(day, at.day)
        and _field_matches(month, at.month, MONTH_NAMES)
        and _field_matches(weekday, (at.weekday() + 1) % 7, DAY_NAMES)   # cron: Sunday is 0
    )


def run(name: str, entry: dict, run_id: str | None = None) -> int:
    """Run one job as a child process.

    A separate process on purpose: a job that leaks memory, wedges, or exits hard takes
    nothing else with it, and SIGTERM on shutdown reaches the SDK's drain handler.
    """
    run_id = run_id or f"run-{uuid.uuid4().hex[:10]}"
    # The registry may store an absolute path (written by `insights up`) or one
    # relative to the platform repo (written by CI). Resolve against the platform
    # root rather than the current directory, or the scheduler only works when it
    # happens to be launched from the right place.
    app_dir = Path(entry["path"])
    if not app_dir.is_absolute():
        app_dir = (PLATFORM / app_dir).resolve()

    env = dict(os.environ)
    env.update(
        INSIGHTS_APP_MANIFEST=str(app_dir / "app.yaml"),
        INSIGHTS_APP=name,
        INSIGHTS_RUN_ID=run_id,
    )
    print(f"[scheduler] starting {name} {run_id}", flush=True)
    result = subprocess.run([sys.executable, "src/main.py"], cwd=app_dir, env=env)
    print(f"[scheduler] {name} {run_id} exit={result.returncode}", flush=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="check once and exit")
    parser.add_argument("--all", action="store_true", help="run every job now, ignoring schedules")
    args = parser.parse_args()

    # apps.local.json (written by `insights up`) shadows apps.json (written by CI),
    # and both may carry `_`-prefixed documentation keys. The edge and the CLI filter
    # those; this did not, so it crashed on startup with
    # AttributeError: 'str' object has no attribute 'get'.
    source = next((p for p in (REGISTRY.with_name("apps.local.json"), REGISTRY) if p.is_file()), None)
    if source is None:
        print("no apps registered - run `insights up` first")
        return 1
    registry = {
        name: entry
        for name, entry in json.loads(source.read_text()).items()
        if not name.startswith("_")
    }

    # Locally, seed the stub warehouse if it is missing. `insights up` and
    # `insights run` both do this; the scheduler did not, so a reviewer following
    # the README on a cold clone got "no such table: hr_compensation". Seeding is
    # idempotent. In a real environment there is nothing to seed and this is a no-op.
    database = PLATFORM / "runtime" / "fakes" / "warehouse" / "warehouse.db"
    if os.environ.get("INSIGHTS_ENV", "local") == "local" and not database.is_file():
        subprocess.run([sys.executable, str(database.with_name("seed.py")), str(database)], check=True)
    jobs = {n: e for n, e in registry.items() if e.get("kind") == "job"}
    print(f"[scheduler] {len(jobs)} job(s): {', '.join(jobs) or '-'}")

    # Run state lives in SQLite, not in a dict on this process.
    #
    # The tick is 30s and `due()` matches to the minute, so without dedupe a job fires
    # TWICE every time - once at :05 and again at :35. That used to be an in-memory
    # dict, which fixed it only within one process lifetime: restart inside the same
    # minute and the job fired twice anyway. It is now a primary-key constraint, so
    # the dedupe survives a restart and two schedulers racing cannot both win.
    # (On Kubernetes this component becomes a CronJob; see ADR-005.)
    state = RunState(PLATFORM / "runtime" / "state" / "scheduler.db")
    reaped = state.reap_abandoned()
    if reaped:
        # Any run still marked in-flight belongs to a scheduler that is gone, and its
        # child died with it. Left alone, one crash blocks that job forever under
        # `concurrency: forbid` - a liveness bug wearing a safety feature's clothes.
        print(f"[scheduler] reaped {reaped} abandoned run(s) from a previous process")

    try:
        while True:
            now = datetime.now(timezone.utc)
            stamp = now.strftime("%Y-%m-%dT%H:%M")
            for name, entry in jobs.items():
                if args.all:
                    run(name, entry)
                    continue
                if not entry.get("schedule") or not due(entry["schedule"], now):
                    continue

                # `concurrency: forbid` - skip this run if the last one is still going.
                # Declared in app.yaml, and until the state store existed it was true
                # only by accident, because run() blocks this loop.
                if entry.get("concurrency", "forbid") == "forbid" and state.in_flight(name):
                    print(f"[scheduler] {name} still running - skipping {stamp} (concurrency: forbid)")
                    continue

                run_id = f"run-{uuid.uuid4().hex[:10]}"
                if not state.claim(name, stamp, run_id):
                    continue                  # already fired this minute, here or before a restart
                code = run(name, entry, run_id)
                state.finish(name, stamp, code)
            if args.once or args.all:
                return 0
            time.sleep(30)
    finally:
        state.close()


if __name__ == "__main__":
    raise SystemExit(main())
