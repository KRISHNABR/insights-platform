#!/usr/bin/env python3
"""Turn a manifest into things that actually exist.

This is where app.yaml stops being a document. Everything a tenant declared becomes
a real object with an owner, and nothing is created by hand - which is the only way
25 tenants stay consistent.
"""
from _contract import arg, declare

raise SystemExit(declare(
    "reconcile",
    inputs={"app": arg("app"), "env": arg("env"), "manifest": arg("manifest", "app.yaml")},
    effects=[
        "access.manage.*        -> the edge's authorization table",
        "access.manage         -> GitHub environment reviewers, and IAM role trust policies",
        "data[]                -> Unity Catalog grant requests, routed to each dataset owner",
        "data[]                -> an IAM policy on the task role, scoped to exactly those datasets",
        "runtime.size          -> task CPU/memory and desired count",
        "web.route             -> a load balancer listener rule",
        "job.*                 -> a scheduler rule: cron, timeout, retries, concurrency, catchup",
        "outputs[]             -> an object-store prefix with a lifecycle rule from `retention`",
    ],
    target=[
        "diff desired against actual and apply only the difference",
        "refuse to widen access without the dataset owner's approval on record",
        "write the reconciliation result to the audit stream",
    ],
))
