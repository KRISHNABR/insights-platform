#!/usr/bin/env python3
"""Prove the thing that just deployed actually works.

The classic silent failure is a deploy that starts cleanly and fails on first use.
/healthz resolves every dataset the app declared and checks its credential arrived,
so that failure surfaces here instead of in front of a user.
"""
from _contract import arg, declare

raise SystemExit(declare(
    "verify",
    inputs={"app": arg("app"), "env": arg("env"), "timeout": arg("timeout", "120")},
    effects=[
        "poll /healthz until every declared dataset resolves, or time out",
        "for a job: confirm the schedule is registered and armed for this environment",
        "fail the deploy - and roll back - rather than reporting a green pipeline",
    ],
    target=["publish the result to the deployment event stream"],
))
