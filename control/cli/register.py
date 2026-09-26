#!/usr/bin/env python3
"""Record what is deployed. `insights status` and the edge both read this."""
from _contract import arg, declare

raise SystemExit(declare(
    "register",
    inputs={"app": arg("app"), "env": arg("env"), "image": arg("image"), "sha": arg("sha")},
    effects=[
        "append to control/registry/apps.json: team, kind, schedule, sdk, image, sha",
        "record the groups that may reach the app, for the edge's layer-1 check",
        "record which datasets it declared, so a dataset owner can see its consumers",
    ],
    target=[
        "make the registry the single answer to 'what is running, and on what version'",
        "surface SDK drift, which is what makes the N-2 support window enforceable",
    ],
))
