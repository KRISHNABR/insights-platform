#!/usr/bin/env python3
"""Roll the image out, and wait to find out whether it worked."""
from _contract import arg, declare

raise SystemExit(declare(
    "deploy",
    inputs={"app": arg("app"), "env": arg("env"), "image": arg("image")},
    effects=[
        "kind: web -> update the service and wait for the rollout to stabilise",
        "kind: job -> register a new task definition; the scheduler picks it up",
        "leave the previous revision in place so a rollback is a pointer change",
    ],
    target=[
        "health-gate the rollout on /healthz, which resolves every declared dataset",
        "roll back automatically if the new revision never becomes healthy",
        "emit a deployment event correlating image digest, commit and approver",
    ],
))
