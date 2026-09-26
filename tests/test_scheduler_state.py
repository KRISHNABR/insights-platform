"""The scheduler's run state must survive a restart.

Three things `app.yaml` declares were, before the state store, true only within one
process lifetime. Each test below is one of them, and each fails if the state goes
back to being a dict on the scheduler process.

Run:  python -m pytest tests/ -q     (from the platform root)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime" / "scheduler"))
from state import RunState                                            # noqa: E402


@pytest.fixture
def db(tmp_path):
    return tmp_path / "scheduler.db"


def test_a_job_fires_once_per_minute(db):
    state = RunState(db)
    assert state.claim("comp-report", "2026-09-28T06:00", "run-a") is True
    assert state.claim("comp-report", "2026-09-28T06:00", "run-b") is False
    assert state.claim("comp-report", "2026-09-28T06:01", "run-c") is True


def test_the_dedupe_survives_a_restart(db):
    """The tick is 30s and `due()` matches to the minute, so a scheduler that
    restarts inside a minute used to fire the job a second time."""
    first = RunState(db)
    assert first.claim("comp-report", "2026-09-28T06:00", "run-a") is True
    first.close()

    restarted = RunState(db)
    assert restarted.claim("comp-report", "2026-09-28T06:00", "run-b") is False


def test_concurrency_forbid_survives_a_restart(db):
    state = RunState(db)
    state.claim("comp-report", "2026-09-28T06:00", "run-a")
    assert state.in_flight("comp-report") is True
    state.close()

    restarted = RunState(db)
    assert restarted.in_flight("comp-report") is True, "a run in flight must still block"


def test_an_abandoned_run_does_not_block_the_job_forever(db):
    """The failure mode this guards: one crash leaves a row saying "still running",
    and `concurrency: forbid` then blocks that job permanently. A safety feature that
    turns into a liveness bug is worse than neither."""
    crashed = RunState(db)
    crashed.claim("comp-report", "2026-09-28T06:00", "run-a")
    crashed.close()                       # never calls finish()

    restarted = RunState(db)
    assert restarted.reap_abandoned() == 1
    assert restarted.in_flight("comp-report") is False
    assert restarted.claim("comp-report", "2026-09-28T06:01", "run-b") is True


def test_an_abandoned_run_is_distinguishable_from_a_successful_one(db):
    state = RunState(db)
    state.claim("comp-report", "2026-09-28T06:00", "run-a")
    state.close()
    state = RunState(db)
    state.reap_abandoned()
    state.claim("comp-report", "2026-09-28T06:01", "run-b")
    state.finish("comp-report", "2026-09-28T06:01", 0)

    history = {row["scheduled_for"]: row for row in state.history()}
    assert history["2026-09-28T06:00"]["exit_code"] is None, "abandoned: no exit code"
    assert history["2026-09-28T06:01"]["exit_code"] == 0
